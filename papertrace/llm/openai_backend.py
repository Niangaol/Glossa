"""OpenAI 兼容后端（云端中转）：S8 起点亮，但默认仍然是 offline。

控制器裁决（原文照录在 task-S8-report.md）：
- R59：model 只从 `PAPERTRACE_LLM` 读；`openai:deepseek` 的冒号后缀只是被容忍的
  写法，**不是模型名**；缺 model → `LLMUnavailable` 且点名 `PAPERTRACE_LLM`，绝不
  猜默认模型名（qwen2.5-coder:7b 是 ollama 的默认）。
- R61：先捕 HTTPError（真实状态码）再捕 URLError 再捕 TimeoutError——HTTPError
  是 URLError 的子类，顺序反了状态码就被吞成笼统网络错误；禁止裸 except
  Exception；超时两种形态（socket.timeout 与 urllib 的 URLError 包装）都要覆盖。
- DeepSeek 没有 embeddings 端点 → embed() 404 或缺 data → LLMUnavailable；只配
  openai 时 s_retr 仍然是 0，出的是黄线不是绿线。

传输层可注入：transport(request) -> {"status": int, "text": str}，其中
request = {"url", "body", "headers", "timeout"}；产品默认 _urllib_transport
（标准库 urllib.request.urlopen，零新依赖）。测试注入假传输，全程不联网。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import ChatResult

ENV_BASE_URL = "PAPERTRACE_OPENAI_BASE_URL"
ENV_API_KEY = "PAPERTRACE_OPENAI_API_KEY"
ENV_MODEL = "PAPERTRACE_LLM"

CHAT_PATH = "/chat/completions"
EMBED_PATH = "/embeddings"

#: 单次请求超时（秒）。判断题要跑很多次，超时太长会让人以为卡死。
DEFAULT_TIMEOUT = 60.0


def _env_or(value, name):
    """显式入参优先；没给才读环境变量。空串等同于没给。"""
    if value:
        return value.strip()
    return (os.environ.get(name) or "").strip()


def _urllib_transport(request):
    """产品默认传输层：标准库 urllib，零新依赖（Constraint 13）。"""
    req = urllib.request.Request(
        request["url"], data=json.dumps(request["body"]).encode("utf-8"),
        headers=request["headers"], method="POST",
    )
    with urllib.request.urlopen(req, timeout=request["timeout"]) as response:
        return {"status": response.status, "text": response.read().decode("utf-8")}


def _error_snippet(exc, limit=200):
    """HTTPError 的响应体片段（中转站的真实原因常在这里），读不动就退回 reason。"""
    text = ""
    fp = getattr(exc, "fp", None)
    if fp is not None:
        try:
            text = fp.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            text = ""
    return text[:limit] or str(exc.reason)



class OpenAICompatBackend:
    """OpenAI 兼容后端。`name == "openai"`，配不齐变量也保持这个名字。

    构造时不校验环境变量：`get_llm()` 必须能返回一个「名字是 openai」的后端，
    让调用方与错误消息说清「你选了 openai 但还缺三样东西」；缺什么在
    `chat()` / `embed()` 第一次被调用时点名（R60）。
    """

    def __init__(self, *, base_url=None, api_key=None, model=None, transport=None, timeout=DEFAULT_TIMEOUT):
        self.name = "openai"
        self._base_url = _env_or(base_url, ENV_BASE_URL)
        self._api_key = _env_or(api_key, ENV_API_KEY)
        self._model = _env_or(model, ENV_MODEL)
        self._transport = _urllib_transport if transport is None else transport
        self._timeout = timeout


    def chat(self, prompt, *, system=None):
        """问一个是/否问题；拿不到可用回答就抛 LLMUnavailable，绝不返回假 yes。"""
        self._require_config()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # temperature=0：判断题要可复现，同一个问题两次问必须得到同一个答案。
        data = self._post_json(CHAT_PATH, {"model": self._model, "messages": messages, "temperature": 0})
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMUnavailable("OpenAI 兼容后端的响应里 choices 为空或缺失：没有可用的回答，不返回假 yes")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("OpenAI 兼容后端的响应缺 message.content 或内容为空：不返回假 yes")
        model = data.get("model")
        if not (isinstance(model, str) and model.strip()):
            # 服务端没回 model 时用本次请求的那个名字（R59：它来自 PAPERTRACE_LLM，不是猜的默认值）。
            model = self._model
        return ChatResult(content, model.strip(), self.name)


    def embed(self, texts):
        """要向量；端点不存在（404）或返回不含 `data` → `LLMUnavailable`。

        DeepSeek 没有 embeddings 端点，所以只配 openai 时 `s_retr` 仍然是 0，
        出的是黄虚线不是绿实线——这一点必须写进 README（R63）。
        """
        self._require_config()
        if not texts:
            return []
        data = self._post_json(EMBED_PATH, {"model": self._model, "input": list(texts)})
        items = data.get("data")
        if not isinstance(items, list) or not items:
            raise LLMUnavailable(
                "OpenAI 兼容后端没有 embeddings 端点或返回不含 data："
                "拿不到向量，s_retr 保持 0（不兜底成假分数）"
            )
        vectors = []
        for index, item in enumerate(items):
            row = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(row, list) or not row:
                raise LLMUnavailable(f"OpenAI 兼容后端 embeddings 第 {index} 项缺 embedding 向量")
            try:
                vectors.append([float(x) for x in row])
            except (TypeError, ValueError) as exc:
                raise LLMUnavailable(
                    f"OpenAI 兼容后端 embeddings 第 {index} 项不是数值向量：{exc}"
                ) from exc
        if len(vectors) != len(texts):
            raise LLMUnavailable(
                f"OpenAI 兼容后端返回 {len(vectors)} 个向量，但请求了 {len(texts)} 条文本："
                "数量对不上，不猜对应关系"
            )
        return vectors


    def _require_config(self):
        """缺 base_url / api_key / model 就点名缺哪个（R59/R60）。"""
        pairs = ((ENV_BASE_URL, self._base_url), (ENV_API_KEY, self._api_key), (ENV_MODEL, self._model))
        missing = [name for name, value in pairs if not value]
        if missing:
            raise LLMUnavailable(
                "OpenAI 兼容后端缺少环境变量：" + "、".join(missing)
                + "。默认仍是 offline；要接云端中转见 README「接云端中转（可选）」。"
            )


    def _post_json(self, path, payload):
        """POST 一个 JSON payload，返回解析后的响应 dict。

        R61 的异常顺序写在这里：先 HTTPError 再 URLError 再 TimeoutError（HTTPError
        是 URLError 子类，顺序反了状态码就被吞成笼统网络错误）；禁止裸 except
        Exception——编程错误必须原样抛出。
        """
        url = self._base_url.rstrip("/") + path
        request = {
            "url": url,
            "body": payload,
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            "timeout": self._timeout,
        }
        try:
            raw = self._transport(request)
        except urllib.error.HTTPError as exc:
            raise LLMUnavailable(
                f"OpenAI 兼容后端返回 HTTP {exc.code}（{url}）：{_error_snippet(exc)}"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMUnavailable(
                    f"OpenAI 兼容后端超时（{self._timeout}s，{url}）：urllib 把超时包成了 URLError"
                ) from exc
            raise LLMUnavailable(f"OpenAI 兼容后端网络错误（{url}）：{exc.reason}") from exc
        except TimeoutError as exc:  # socket.timeout 就是 TimeoutError（3.10+）
            raise LLMUnavailable(f"OpenAI 兼容后端超时（{self._timeout}s，{url}）") from exc
        if not isinstance(raw, dict):
            raise LLMUnavailable(
                f"OpenAI 兼容后端的传输层返回了 {type(raw).__name__}，不是响应 dict"
            )
        status = raw.get("status")
        if not (isinstance(status, int) and 200 <= status < 300):
            raise LLMUnavailable(
                f"OpenAI 兼容后端返回 HTTP {status}（{url}）：{str(raw.get('text'))[:200]}"
            )
        try:
            data = json.loads(raw.get("text"))
        except (TypeError, ValueError) as exc:
            raise LLMUnavailable(f"OpenAI 兼容后端的响应不是合法 JSON（{url}）：{exc}") from exc
        if not isinstance(data, dict):
            raise LLMUnavailable(f"OpenAI 兼容后端的响应 JSON 顶层不是对象（{url}）")
        return data
