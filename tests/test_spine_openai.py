"""S8：OpenAI 兼容后端（点亮开关，但默认仍然是 offline）。

控制器裁决（原文照录在 task-S8-report.md）：
- R59：model 只从 `PAPERTRACE_LLM` 读。`PAPERTRACE_LLM_BACKEND=openai:deepseek`
  的冒号后缀只是被容忍的写法，**不是模型名**；缺 model → `LLMUnavailable`
  且点名 `PAPERTRACE_LLM`，绝不猜默认模型名（`qwen2.5-coder:7b` 是 ollama
  的默认，openai 路径不许套用）。
- R60：`tests/test_llm_hint.py` 一行不动（它钉的是 ollama 仍未实现）；
  被打破的只有 `tests/test_llm_offline.py:30-36`，改法是加强不是放宽。
- R61：异常顺序必须先 `HTTPError`（报真实状态码）再捕 `URLError` 再捕 `TimeoutError`；
  禁止裸 `except Exception`；超时两种形态（`socket.timeout` 与 urllib 的
  `URLError` 包装）都要覆盖。
- R62：协议检查用 `isinstance(b, LLMBackend)`，不退化成 `hasattr`。
- R63/R64：README 新增「接云端中转（可选）」小节；`_offline_hint` 改成如实描述。

测试全程不联网（Constraint 2 + 本 dispatch 的环境节）：传输层可注入，所有
用例都注入假传输；另有一条 autouse fixture 把 `urllib.request.urlopen`
换成抛 AssertionError 的哨兵，哪条用例偷偷打网都会当场炸。
"""

import io
import json
import pathlib
import socket
import urllib.error
import urllib.request

import pytest

from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import LLMBackend, OfflineBackend, get_llm

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 四个环境变量的字面名。测试钉字面契约，不 import 产品常量——两边一起错就白测了。
ENV_BACKEND = "PAPERTRACE_LLM_BACKEND"
ENV_BASE_URL = "PAPERTRACE_OPENAI_BASE_URL"
ENV_API_KEY = "PAPERTRACE_OPENAI_API_KEY"
ENV_MODEL = "PAPERTRACE_LLM"

BASE_URL = "https://relay.example.com/v1"
API_KEY = "sk-test-not-a-real-key"
MODEL = "deepseek-chat"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """本文件任何用例都不许碰网络：urlopen 一被调用就炸。"""

    def _boom(*args, **kwargs):
        raise AssertionError("测试不许联网：请注入假传输，或另装一个假 urlopen")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)


@pytest.fixture
def backend_mod():
    """延迟 import `papertrace.llm.openai_backend`。

    这样「模块还不存在」表现为每个用例失败（测试级红），而不是收集期
    ImportError——后者会让整份文件一个用例都不跑，证明不了任何判据。
    """
    import papertrace.llm.openai_backend as module

    return module


class FakeTransport:
    """可注入的传输层：`transport(request: dict) -> dict`。

    单实例跨调用保持状态——每次新建实例会重置计数器，让人以为实现漏了
    某条路径（控制器踩过）。`requests` 同时用来证明被测路径真被走到。
    """

    def __init__(self, reply=None, *, raises=None):
        self.reply = reply
        self.raises = raises
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return self.reply


def _backend(backend_mod, reply=None, *, raises=None, **overrides):
    """构造一个注入了假传输的后端；返回 (backend, transport)。"""
    transport = FakeTransport(reply, raises=raises)
    kwargs = {
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "model": MODEL,
        "transport": transport,
    }
    kwargs.update(overrides)
    return backend_mod.OpenAICompatBackend(**kwargs), transport


def _chat_reply(
    text="Verdict: yes\nEvidence: torch.softmax(torch.matmul(q, k.transpose(-2, -1)))",
    *,
    model="deepseek-chat-pro",
):
    return {
        "status": 200,
        "text": json.dumps(
            {
                "id": "chatcmpl-fake",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
            }
        ),
    }


def _embed_reply(dim=2, count=2):
    return {
        "status": 200,
        "text": json.dumps(
            {
                "model": MODEL,
                "data": [{"embedding": [0.1 * (i + 1)] * dim} for i in range(count)],
            }
        ),
    }


# --------------------------------------------------------------------------
# 配置缺失：缺哪个变量就点名哪个，而且在发起任何请求之前就拒绝
# --------------------------------------------------------------------------
@pytest.mark.parametrize("missing", [ENV_BASE_URL, ENV_API_KEY, ENV_MODEL])
def test_missing_env_raises_llm_unavailable(backend_mod, monkeypatch, missing):
    for name in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
        monkeypatch.delenv(name, raising=False)
    params = {"base_url": BASE_URL, "api_key": API_KEY, "model": MODEL}
    params[
        {ENV_BASE_URL: "base_url", ENV_API_KEY: "api_key", ENV_MODEL: "model"}[missing]
    ] = None
    backend, transport = _backend(backend_mod, _chat_reply(), **params)
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("Attention 的 softmax 对应哪一行？")
    assert missing in str(excinfo.value)
    assert transport.requests == [], "缺配置必须在发请求之前就拒绝"


def test_chat_parses_first_choice(backend_mod):
    backend, transport = _backend(backend_mod, _chat_reply())
    result = backend.chat("Attention 的 softmax 对应哪一行？")
    assert result.text.startswith("Verdict: yes")
    assert result.backend == "openai"
    # R59：model 写服务端返回的真实名字，不是我们请求的那个
    assert result.model == "deepseek-chat-pro"
    assert len(transport.requests) == 1, "假传输必须真被走到，否则测的是兜底路径"
    request = transport.requests[0]
    assert request["url"] == BASE_URL + "/chat/completions"
    assert request["body"]["model"] == MODEL
    assert request["body"]["temperature"] == 0
    assert request["body"]["messages"][-1] == {
        "role": "user",
        "content": "Attention 的 softmax 对应哪一行？",
    }
    assert request["headers"]["Authorization"] == f"Bearer {API_KEY}"


def test_system_prompt_is_sent_as_the_first_message(backend_mod):
    backend, transport = _backend(backend_mod, _chat_reply())
    backend.chat("hi", system="你是论文与代码的对账员")
    messages = transport.requests[0]["body"]["messages"]
    assert messages[0] == {"role": "system", "content": "你是论文与代码的对账员"}
    assert messages[-1]["role"] == "user"


# --------------------------------------------------------------------------
# 传输层错误：R61 的顺序在这里被钉住
# --------------------------------------------------------------------------
def test_non_200_raises(backend_mod):
    backend, transport = _backend(backend_mod, {"status": 500, "text": '{"error":"relay exploded"}'})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "500" in str(excinfo.value)
    assert transport.requests, "非 200 也必须真的走到传输层"


def test_http_error_reports_the_real_status_code(backend_mod):
    """R61：HTTPError 是 URLError 的子类，必须先捕它，否则状态码被吞成笼统网络错误。"""
    body = json.dumps({"error": {"message": "insufficient balance"}}).encode("utf-8")
    exc = urllib.error.HTTPError(
        BASE_URL + "/chat/completions", 402, "Payment Required", {}, io.BytesIO(body)
    )
    backend, transport = _backend(backend_mod, raises=exc)
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    message = str(excinfo.value)
    assert "402" in message
    assert "insufficient balance" in message, "中转站的真实原因要带到消息里"
    assert "网络错误" not in message
    assert transport.requests


def test_timeout_raises(backend_mod):
    """R61：第一种超时形态——socket.timeout（3.10 起就是 TimeoutError）。"""
    backend, transport = _backend(backend_mod, raises=socket.timeout("timed out"))
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "超时" in str(excinfo.value)
    assert transport.requests


def test_urllib_wrapped_timeout_raises(backend_mod):
    """R61：第二种超时形态——urllib 把超时包成 URLError(reason=TimeoutError)。"""
    backend, transport = _backend(
        backend_mod, raises=urllib.error.URLError(socket.timeout("timed out"))
    )
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "超时" in str(excinfo.value)
    assert transport.requests


def test_plain_network_error_raises(backend_mod):
    backend, _ = _backend(backend_mod, raises=urllib.error.URLError("connection refused"))
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "网络错误" in str(excinfo.value)


def test_programming_error_is_not_swallowed(backend_mod):
    """R61：禁止裸 except Exception——编程错误必须原样抛出，不许变成「后端不可用」。"""
    backend, _ = _backend(backend_mod, raises=RuntimeError("bug in my code"))
    with pytest.raises(RuntimeError, match="bug in my code"):
        backend.chat("hi")


# --------------------------------------------------------------------------
# 响应内容不合法：各自报各自的具体原因，绝不兜底成假 yes
# --------------------------------------------------------------------------
def test_malformed_json_raises(backend_mod):
    backend, transport = _backend(backend_mod, {"status": 200, "text": "<html>502 Bad Gateway</html>"})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "JSON" in str(excinfo.value)
    assert transport.requests


def test_empty_choices_raises(backend_mod):
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps({"choices": []})})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "choices" in str(excinfo.value)


def test_missing_choices_raises(backend_mod):
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps({"id": "x"})})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "choices" in str(excinfo.value)


def test_missing_message_content_raises(backend_mod):
    """choices 有了但 message.content 是空的：同样不许兜底成假 yes。"""
    payload = {"choices": [{"index": 0, "message": {"role": "assistant", "content": ""}}]}
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps(payload)})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert "content" in str(excinfo.value)


def test_model_falls_back_to_the_requested_name_when_server_omits_it(backend_mod):
    """Ruling：服务端没回 model 时用本次请求的名字（它来自 PAPERTRACE_LLM，不是猜的默认值）。"""
    payload = {"choices": [{"message": {"content": "Verdict: no"}}]}
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps(payload)})
    assert backend.chat("hi").model == MODEL


# --------------------------------------------------------------------------
# embeddings：DeepSeek 没有这个端点，拿不到就说拿不到
# --------------------------------------------------------------------------
def test_embed_returns_vectors(backend_mod):
    backend, transport = _backend(backend_mod, _embed_reply(count=2))
    vectors = backend.embed(["QK^T", "softmax"])
    assert vectors == [[0.1, 0.1], [0.2, 0.2]]
    assert all(isinstance(v, float) for row in vectors for v in row)
    request = transport.requests[0]
    assert request["url"] == BASE_URL + "/embeddings"
    assert request["body"] == {"model": MODEL, "input": ["QK^T", "softmax"]}


def test_embed_empty_input_makes_no_request(backend_mod):
    backend, transport = _backend(backend_mod, _chat_reply())
    assert backend.embed([]) == []
    assert transport.requests == []


def test_embed_404_raises_llm_unavailable(backend_mod):
    """DeepSeek 没有 embeddings 端点：404 → LLMUnavailable，s_retr 保持 0。"""
    backend, transport = _backend(backend_mod, {"status": 404, "text": '{"error":"not found"}'})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.embed(["QK^T"])
    assert "404" in str(excinfo.value)
    assert transport.requests


def test_embed_without_data_raises_llm_unavailable(backend_mod):
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps({"model": MODEL})})
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.embed(["QK^T"])
    assert "embeddings" in str(excinfo.value) or "data" in str(excinfo.value)


def test_embed_count_mismatch_raises(backend_mod):
    """少返回一条向量就拒绝：与 S6 的 R54 守卫同标准，不猜对应关系。"""
    backend, _ = _backend(backend_mod, _embed_reply(count=1))
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.embed(["a", "b"])
    assert "2" in str(excinfo.value) and "1" in str(excinfo.value)


def test_embed_non_numeric_vector_raises(backend_mod):
    payload = {"data": [{"embedding": ["not-a-number"]}]}
    backend, _ = _backend(backend_mod, {"status": 200, "text": json.dumps(payload)})
    with pytest.raises(LLMUnavailable):
        backend.embed(["a"])


# --------------------------------------------------------------------------
# 协议与分派
# --------------------------------------------------------------------------
def test_backend_satisfies_protocol(backend_mod):
    """R62：LLMBackend 是 runtime_checkable Protocol，用 isinstance 检查。"""
    backend, _ = _backend(backend_mod, _chat_reply())
    assert isinstance(backend, LLMBackend)
    assert backend.name == "openai"


def test_protocol_check_has_teeth(backend_mod):
    """R62：缺 embed 的类必须过不了 isinstance——否则这条检查是空转的。"""

    class _NoEmbed:
        name = "broken"

        def chat(self, prompt, *, system=None):
            return None

    assert not isinstance(_NoEmbed(), LLMBackend)


def test_get_llm_dispatches_on_env(backend_mod, monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "openai")
    monkeypatch.setenv(ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(ENV_API_KEY, API_KEY)
    monkeypatch.setenv(ENV_MODEL, MODEL)
    backend = get_llm()
    assert isinstance(backend, backend_mod.OpenAICompatBackend)
    assert backend.name == "openai"


def test_get_llm_tolerates_the_colon_suffix_as_backend_head(backend_mod, monkeypatch):
    """R59：`openai:deepseek` 的 head 才是 backend 名，后缀不是模型名。"""
    monkeypatch.setenv(ENV_BACKEND, "openai:deepseek")
    monkeypatch.setenv(ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(ENV_API_KEY, API_KEY)
    monkeypatch.setenv(ENV_MODEL, MODEL)
    assert isinstance(get_llm(), backend_mod.OpenAICompatBackend)


def test_get_llm_keeps_ollama_offline(monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "ollama")
    backend = get_llm()
    assert isinstance(backend, OfflineBackend)
    assert backend.name == "offline"


def test_offline_is_still_the_default(monkeypatch):
    for name in (ENV_BACKEND, ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
        monkeypatch.delenv(name, raising=False)
    backend = get_llm()
    assert isinstance(backend, OfflineBackend)
    assert backend.name == "offline"
    with pytest.raises(LLMUnavailable):
        backend.chat("hi")


def test_model_comes_from_papertrace_llm_not_the_suffix(backend_mod, monkeypatch):
    """R59：冒号后缀不是模型名；请求体里的 model 必须来自 PAPERTRACE_LLM。"""
    monkeypatch.setenv(ENV_BACKEND, "openai:deepseek")
    monkeypatch.setenv(ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(ENV_API_KEY, API_KEY)
    monkeypatch.setenv(ENV_MODEL, "deepseek-chat")
    transport = FakeTransport(_chat_reply(model="deepseek-chat"))
    backend = backend_mod.OpenAICompatBackend(transport=transport)
    backend.chat("hi")
    assert transport.requests[0]["body"]["model"] == "deepseek-chat"


def test_missing_model_is_not_guessed(backend_mod, monkeypatch):
    """R59：缺 PAPERTRACE_LLM 就点名报错，绝不套用 ollama 的默认模型名。"""
    monkeypatch.delenv(ENV_MODEL, raising=False)
    monkeypatch.setenv(ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(ENV_API_KEY, API_KEY)
    # 注意：base_url / api_key 显式给，model 故意不给——否则测的是「显式入参优先」，
    # 不是「缺 PAPERTRACE_LLM」。
    transport = FakeTransport(_chat_reply())
    backend = backend_mod.OpenAICompatBackend(base_url=BASE_URL, api_key=API_KEY, transport=transport)
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("hi")
    assert ENV_MODEL in str(excinfo.value)
    assert "qwen" not in str(excinfo.value).lower()
    assert transport.requests == []


# --------------------------------------------------------------------------
# 网络纪律与预算
# --------------------------------------------------------------------------
def test_no_network_in_tests(backend_mod):
    """哨兵装上了；再把每条分支都跑一遍，看有没有哪条偷偷回到默认传输层。"""
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://relay.example.com/v1/chat/completions")
    replies = [
        _chat_reply(),
        {"status": 500, "text": "{}"},
        {"status": 200, "text": "not json"},
        {"status": 200, "text": json.dumps({"choices": []})},
        _embed_reply(count=2),
        {"status": 404, "text": "{}"},
    ]
    for reply in replies:
        backend, _ = _backend(backend_mod, reply)
        for call in (lambda: backend.chat("hi"), lambda: backend.embed(["a", "b"])):
            try:
                call()
            except LLMUnavailable:
                pass  # 只有 LLMUnavailable 可以吃；AssertionError 会照原样炸出去


def test_default_transport_is_urllib_urlopen(backend_mod, monkeypatch):
    """产品默认传输层就是 urllib.request.urlopen（可注入只发生在测试里）。"""
    seen = {}

    class _Response:
        status = 200

        def read(self):
            return json.dumps(
                {"model": MODEL, "choices": [{"message": {"content": "Verdict: no"}}]}
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["authorization"] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    backend = backend_mod.OpenAICompatBackend(base_url=BASE_URL, api_key=API_KEY, model=MODEL)
    result = backend.chat("hi")
    assert result.text == "Verdict: no"
    assert result.model == MODEL
    assert seen["url"] == BASE_URL + "/chat/completions"
    assert seen["body"]["model"] == MODEL
    assert seen["authorization"] == f"Bearer {API_KEY}"
    assert seen["timeout"] and seen["timeout"] > 0


def test_product_files_stay_within_the_line_budget():
    """Constraint 1：单源文件 ≤200 行（splitlines 口径，不是 Get-Content .Count）。"""
    for name in ("papertrace/llm/openai_backend.py", "papertrace/llm/client.py"):
        lines = (REPO / name).read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 200, f"{name} 有 {len(lines)} 行，超过 200 行预算"
