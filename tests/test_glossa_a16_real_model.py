"""R517/R518/R519：AI 讲解第一次接真模型时才暴露的三条缝。

- R517：真后端只有 chat()（ChatResult），ai_pipeline 要的是 complete() -> str；不包适配器
  时配了真模型跑 --ai 直接 AttributeError（离线桩有 complete，所以测试一直没抓到这个）。
- R518：页头「未溯源 N 处」原来只数 <main> 里的黄标，可图注、卡片文字、连线标签、节标题、
  模型说明这五处数字既不标黄也不计数——真模型在这些位置写数字，页头仍会写 0。
- R519：桩跑出来的页头同时写「本页由模型分节撰写」和「本页由离线桩生成」，两句话直接冲突。
"""

import json
import pathlib
import shutil

import pytest

from glossa import facts as facts_mod
from glossa.explain import ai_pipeline, fake_llm, llm_config
from papertrace.exceptions import BuildError
from papertrace.llm.client import ChatResult
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"


@pytest.fixture()
def repo():
    dst = scratch_dir("a16-real")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    return facts_mod.build_repo_doc(repo)


class Echo:
    """自由回包：不依赖离线桩，任何提示词都回同一句（真模型的形状）。"""

    name = "openai"

    def __init__(self, text="好的"):
        self.text, self.calls = text, 0

    def chat(self, prompt, *, system=None):
        self.calls += 1
        return ChatResult(self.text, "step-5-preview", "openai")


class ChatOnly(Echo):
    """形状与真后端一致：只有 chat()，没有 complete()；页面用例里转发给离线桩造真 JSON。"""

    def __init__(self, inner=None):
        super().__init__()
        self.inner = inner

    def chat(self, prompt, *, system=None):
        self.calls += 1
        text = self.text if self.inner is None else self.inner.complete(prompt, system or "")
        return ChatResult(text, "step-5-preview", "openai")


class SectionLLM(fake_llm.FakeLLM):
    """第一节交指定的 title/figures，其余节只写一句正文（协议形状与真模型一致）。"""

    def __init__(self, figures=(), title="规模"):
        super().__init__()
        self.figures, self.title, self.sections = list(figures), title, 0

    def complete(self, prompt, system=""):
        if "这一节的素材包" in str(prompt):
            self.sections += 1
            pack = fake_llm._load(prompt)
            head = self.title if self.sections == 1 else str((pack.get("section") or {}).get("title") or "")
            return json.dumps({"title": head, "html": "<p>正文</p>",
                               "figures": self.figures if self.sections == 1 else [],
                               "notes": []}, ensure_ascii=False)
        return super().complete(prompt, system)


# R517：适配器把 chat() 接成 complete()
def test_chat_adapter_turns_chat_into_complete():
    wrapper = ai_pipeline.ChatAdapter(Echo("把这句话返回"))
    text = wrapper.complete("把这句话返回", "系统提示")
    assert isinstance(text, str) and text.strip()
    assert wrapper.name == "openai"


def test_chat_adapter_rejects_empty_text():
    class Silent:
        name = "openai"

        def chat(self, prompt, *, system=None):
            return ChatResult("   ", "m", "openai")

    with pytest.raises(BuildError, match="空文本"):
        ai_pipeline.ChatAdapter(Silent()).complete("x")


def test_as_completer_keeps_fake_and_wraps_chat_only():
    fake = fake_llm.FakeLLM()
    assert ai_pipeline.as_completer(fake) is fake
    assert isinstance(ai_pipeline.as_completer(ChatOnly()), ai_pipeline.ChatAdapter)


def test_run_ai_works_with_a_chat_only_backend(doc, repo):
    result = ai_pipeline.run_ai(doc, ai_pipeline.as_completer(ChatOnly(fake_llm.FakeLLM())),
                                "magazine", root=repo)
    assert result["sections"] and result["mode"] == "ai"
    assert "<main" in result["html"]


def test_build_llm_wraps_the_real_backend(doc, repo, monkeypatch):
    monkeypatch.setattr(llm_config, "resolve", lambda **kw: llm_config.Config(
        "openai", "https://example.invalid/v1", "k", "m", "glossa"))
    monkeypatch.setattr(llm_config, "ready", lambda cfg: True)
    monkeypatch.setattr(ai_pipeline, "backend", lambda: Echo("答"))
    llm = ai_pipeline.build_llm("openai")
    assert hasattr(llm, "complete")
    assert llm.complete("随便问一句").strip()


# R518：程序画/贴的地方里的数字也要计入「未溯源」
def test_number_in_a_card_text_is_counted(doc, repo):
    label = doc["meta"]["repo"]["root_name"]
    fig = {"pattern": "cards", "caption": "关键文件",
           "cards": [{"label": label, "text": "这里有 99999 个文件"}]}
    result = ai_pipeline.run_ai(doc, SectionLLM([fig]), "magazine", root=repo)
    assert result["unmarked"] >= 1
    assert "未溯源 0 处" not in result["html"]
    assert any("查不到出处" in note for note in result["notes"]), result["notes"]


def test_number_in_the_caption_and_title_is_counted(doc, repo):
    label = doc["meta"]["repo"]["root_name"]
    fig = {"pattern": "layered", "caption": "一共 88888 个节点",
           "nodes": [{"id": label, "label": label}]}
    result = ai_pipeline.run_ai(doc, SectionLLM([fig], title="第 77777 节"), "magazine", root=repo)
    assert result["unmarked"] >= 2
    assert "未溯源 0 处" not in result["html"]


def test_stub_pages_still_report_zero(doc, repo):
    result = ai_pipeline.run_ai(doc, fake_llm.FakeLLM(), "magazine", root=repo)
    assert result["untraced"] == 0 and result["unmarked"] == 0
    assert "未溯源 0 处" in result["html"]


# R519：桩的页头不许同时出现「模型分节撰写」与「离线桩生成」
def test_stub_page_header_does_not_claim_a_model_wrote_it(doc, repo):
    html = ai_pipeline.run_ai(doc, fake_llm.FakeLLM(), "magazine", root=repo)["html"]
    assert "本页由模型分节撰写" not in html
    assert "离线桩分节组装" in html and "未调用真实模型" in html


def test_real_backend_page_keeps_the_model_badge(doc, repo):
    html = ai_pipeline.run_ai(doc, ai_pipeline.as_completer(ChatOnly(fake_llm.FakeLLM())),
                              "magazine", root=repo)["html"]
    assert "本页由模型分节撰写" in html
    assert "离线桩分节组装" not in html     # 桩的徽章句不许混进真模型页（正文里的桩文案不算）


# R517：配置不全时点名「后端变量」也缺，不只报三个连接参数
def test_missing_backend_is_named_in_the_error(monkeypatch):
    monkeypatch.delenv("GLOSSA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    with pytest.raises(BuildError) as caught:
        ai_pipeline.build_llm("openai")
    text = str(caught.value)
    assert "GLOSSA_LLM_BACKEND" in text and "openai" in text


# R517：慢的推理模型要能把超时调长；写错值响亮报错
def test_timeout_env_is_read_and_validated(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_TIMEOUT", raising=False)
    monkeypatch.setenv("GLOSSA_LLM_TIMEOUT", "300")
    assert llm_config.timeout_seconds() == 300.0
    monkeypatch.setenv("GLOSSA_LLM_TIMEOUT", "五分钟")
    with pytest.raises(ValueError, match="不是秒数"):
        llm_config.timeout_seconds()
    monkeypatch.setenv("GLOSSA_LLM_TIMEOUT", "-1")
    with pytest.raises(ValueError, match="正数"):
        llm_config.timeout_seconds()

# R520：推理模型把 token 花在思维链上，不设上限就慢慢写满（实测 2000 时 content 为空）
def test_max_tokens_env_is_read_and_validated(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("GLOSSA_LLM_MAX_TOKENS", "8000")
    assert llm_config.max_tokens() == 8000
    monkeypatch.setenv("GLOSSA_LLM_MAX_TOKENS", "很多")
    with pytest.raises(ValueError, match="不是整数"):
        llm_config.max_tokens()
    monkeypatch.setenv("GLOSSA_LLM_MAX_TOKENS", "0")
    with pytest.raises(ValueError, match="正整数"):
        llm_config.max_tokens()


def _sent_body(monkeypatch, **kwargs):
    from papertrace.llm import openai_backend
    sent = {}

    def transport(request):
        sent.update(request["body"])
        return {"status": 200, "text": json.dumps(
            {"choices": [{"message": {"content": "好"}}], "model": "m"})}

    monkeypatch.setenv("PAPERTRACE_OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("PAPERTRACE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("PAPERTRACE_LLM", "m")
    openai_backend.OpenAICompatBackend(transport=transport, **kwargs).chat("问一句")
    return sent


def test_backend_payload_carries_max_tokens(monkeypatch):
    assert _sent_body(monkeypatch, max_tokens=8000)["max_tokens"] == 8000


def test_backend_payload_stays_the_same_without_max_tokens(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_MAX_TOKENS", raising=False)
    assert "max_tokens" not in _sent_body(monkeypatch)

# R524：推理模型偶发返回空 content（token 全花在思维链上）——重试一次，别把空串当正文
def test_chat_adapter_retries_once_on_an_unavailable_backend():
    from papertrace.exceptions import LLMUnavailable

    class Flaky(Echo):
        def __init__(self):
            super().__init__("第二次成功")
            self.fail = True

        def chat(self, prompt, *, system=None):
            self.calls += 1
            if self.fail:
                self.fail = False
                raise LLMUnavailable("响应缺 message.content 或内容为空")
            return ChatResult(self.text, "m", "openai")

    wrapper = ai_pipeline.ChatAdapter(Flaky())
    assert wrapper.complete("问") == "第二次成功"
    assert wrapper.backend.calls == 2


def test_chat_adapter_gives_up_after_the_second_empty_answer():
    class Blank(Echo):
        def chat(self, prompt, *, system=None):
            self.calls += 1
            return ChatResult("   ", "m", "openai")

    wrapper = ai_pipeline.ChatAdapter(Blank())
    with pytest.raises(BuildError, match="GLOSSA_LLM_MAX_TOKENS"):
        wrapper.complete("问")
    assert wrapper.backend.calls == 2
