"""S7：判断题 judge——只问一个是/否问题，只接受 yes/no + 依据。

控制器裁决（原文照录在 task-S7-report.md）：
- R47：`judge(term, snippet)` 的 `term` 是**公式项的文本字符串**（S9 传的就是
  它给 S6 的那个 text），不是 Term 对象也不是 dict。签名里绝不允许出现
  `mapping: dict`，也不许提供任何「一次吐出整张映射表」的接口。
- R48：`JUDGE_PROMPT` 是冻结文本，一个字都不许改；`judge_prompt(term_text,
  snippet)` = JUDGE_PROMPT 原文 + 一段固定格式的输入区；
  `JUDGE_PROMPT_VERSION` 冻结为 "judge-v1"。`DRILL_PROMPT` 一个字都不许动
  （铁律：初次与深钻必须是两个常量，禁止混用）。
- R49：`JudgeResult` 没有 reason 字段。`test_offline_judge_scores_zero_with_reason`
  断言的是「offline 下 judge 返回 JudgeResult(False, "") 且 judge_score == 0.0」；
  **reason 字符串是 S9 的责任**（写进 unresolved/anchor），judge 不吐 reason。
- R50：evidence 取 `Evidence:` 行的其余文本 → strip 外侧空白 → 按**字符数**
  （Python `len(str)`，不是字节）截断到 `EVIDENCE_MAX_CHARS=40`。
- R51：Verdict 逐行找 strip 后以 `Verdict:` / `Verdict：`（全角冒号）开头的行，
  键与值都大小写不敏感；取该值的**首 token**，只有 `yes` → True，其余一律 False。
  绝不从自由文本里搜 yes；也不要对整个响应取首 token（那是 `Verdict:`）。
- R53：`get_llm().chat(...)` 返回 `ChatResult` 不是 str，必须取 `.text`。
- R57：`judge_score(result)` = yes 且 evidence 非空且非纯空白 → 1.0；否则 0.0。

测试全程不联网：offline 用真 OfflineBackend，有回复用注入式假后端
（Constraint 2：测试替身只允许出现在 tests/ 下）。假后端按 R43 的手法
monkeypatch **judge.py 自己引用的** `get_llm`，绝不改 client.py。
"""

import hashlib
import inspect
import pathlib

import pytest

from papertrace.align import judge as judge_module
from papertrace.align.judge import JudgeResult, judge, judge_score
from papertrace.constants import EVIDENCE_MAX_CHARS
from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import ChatResult
from papertrace.llm.prompts import DRILL_PROMPT, JUDGE_PROMPT, JUDGE_PROMPT_VERSION, judge_prompt

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 黄金主路径上的真实形状（GC7）：论文公式项 vs fx 图里的算子片段。
_TERM = "Softmax(QK^T / sqrt(d_k))"
_SNIPPET = "attn = torch.softmax(torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(d_k), dim=-1)"


class FakeBackend:
    """实现 LLMBackend 协议的测试后端：按脚本返回可复现的回答，不联网。

    单实例跨多次调用保持状态（控制器踩过：每次新建实例会让计数重置，
    于是「该被触发的断言」根本没被触发）。`replies` 记录交给 judge 的
    ChatResult 原文，用来证明 R53——拿到的是 ChatResult 而不是 str。
    """

    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []
        self.replies: list[ChatResult] = []

    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult:
        self.prompts.append(prompt)
        result = ChatResult(self.reply, "fake-model", "fake")
        self.replies.append(result)
        return result

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("判断题路径不该调 embed")


class UnavailableBackend:
    """只有 chat 抛 LLMUnavailable 的后端：模拟配了模型但后端不可用。"""

    name = "unavailable"

    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult:
        raise LLMUnavailable("fake: 后端不可用")

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("判断题路径不该调 embed")


def _patch(monkeypatch, reply: str) -> FakeBackend:
    """注入假后端：换掉 judge.py 自己引用的 get_llm，同一个实例跨调用复用。"""
    backend = FakeBackend(reply)
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    return backend


# --------------------------------------------------------------------------
# prompt 侧（R48）
# --------------------------------------------------------------------------


def test_judge_prompt_is_yes_no():
    """判断题不是生成题：prompt 必须写死「只能回答 yes / no」。"""
    assert "只能回答 yes / no" in JUDGE_PROMPT
    assert "请列出对应关系" not in JUDGE_PROMPT
    built = judge_prompt(_TERM, _SNIPPET)
    assert "只能回答 yes / no" in built
    assert "请列出对应关系" not in built


def test_judge_prompt_version_is_frozen():
    """R48：版本号冻结为 "judge-v1"——prompt 一改就要能对回是哪一版。"""
    assert JUDGE_PROMPT_VERSION == "judge-v1"


def test_judge_prompt_is_frozen_text_plus_input_block():
    """R48：judge_prompt = JUDGE_PROMPT 原文 + 固定格式输入区，原文一字不改。"""
    built = judge_prompt(_TERM, _SNIPPET)
    assert built.startswith(JUDGE_PROMPT)
    # 输入区把两个入参原样嵌进去
    assert _TERM in built
    assert _SNIPPET in built
    assert built.index(_TERM) > built.index("Verdict: yes|no")
    # 严格两行格式只许来自冻结的 JUDGE_PROMPT，输入区不许再写一套
    assert built.count("Verdict: yes|no") == 1
    assert built.count("Evidence: <≤40 字的依据>") == 1


#: 两个冻结 prompt 的整段正文 sha256（口径 hashlib.sha256(S.encode("utf-8")).hexdigest()）。
#: 控制器在 HEAD=3bda705 上实测的当前正确值。**改正文就要更新这两个 hash，
#: 并同时升 JUDGE_PROMPT_VERSION**——否则下面这条必红，不会让你悄无声息地漂移。
_JUDGE_PROMPT_SHA256 = "2cfab369b5d7ac7d6e567e77173296e98c4383a1f3fcfc7a3fda49e6bc325c5b"
_DRILL_PROMPT_SHA256 = "911f1bcc900fa2913f972c7d9efced92b5486f4008a40bbe41d2fb4fb7b9331e"


def test_frozen_prompt_texts_are_pinned_by_hash():
    """R48 + R66：两个冻结 prompt 的整段正文用 sha256 钉死。

    `test_judge_prompt_is_frozen_text_plus_input_block` 的核心断言
    `built.startswith(JUDGE_PROMPT)` **按构成为真**——judge_prompt 本身就是
    `f"{JUDGE_PROMPT}\n…"`，与 JUDGE_PROMPT 的正文内容毫无关系。于是改冻结
    正文的任何一句（哪怕把「只能回答 yes / no」改成「尽量回答」）都没有测试会红，
    R48「一字不许改」只剩人工纪律。

    这里把整段正文钉成单一事实来源：不用字面量副本（那会让 prompt 有两份、
    以后改 prompt 要改两处），一行 sha256 断言即可。**两个常量都要钉**——
    DRILL_PROMPT 同样是冻结的。

    **改正文就要更新这两个 hash，并同时升 JUDGE_PROMPT_VERSION。**
    """
    assert (
        hashlib.sha256(JUDGE_PROMPT.encode("utf-8")).hexdigest()
        == _JUDGE_PROMPT_SHA256
    ), "JUDGE_PROMPT 正文被改了：更新 _JUDGE_PROMPT_SHA256 并升 JUDGE_PROMPT_VERSION"
    assert (
        hashlib.sha256(DRILL_PROMPT.encode("utf-8")).hexdigest()
        == _DRILL_PROMPT_SHA256
    ), "DRILL_PROMPT 正文被改了：更新 _DRILL_PROMPT_SHA256"


def test_first_and_drill_prompts_stay_separate_constants():
    """铁律：初次（L0–L2）与深钻（L3）必须是两个常量，禁止混用。

    混用会让深钻丢掉父节点结论，退化成「再问一遍」。本 Task 只许动
    JUDGE_PROMPT 侧，DRILL_PROMPT 一个字都不许碰。
    """
    assert DRILL_PROMPT is not JUDGE_PROMPT
    assert DRILL_PROMPT != JUDGE_PROMPT
    assert "Verdict" not in DRILL_PROMPT
    assert JUDGE_PROMPT not in DRILL_PROMPT
    # DRILL_PROMPT 冻结：它仍然带着 L3 的三段式输出要求
    assert "Probe（实测）" in DRILL_PROMPT
    assert "Equivalent（符号等价）" in DRILL_PROMPT
    assert "Adversarial（你自己的反驳）" in DRILL_PROMPT


# --------------------------------------------------------------------------
# 两行格式解析（R51 / S19）
# --------------------------------------------------------------------------


def test_two_line_format_is_parsed(monkeypatch):
    """规格点名的正例：`Verdict: yes` + `Evidence: …` → yes 且依据正确。"""
    _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的 QK^T 矩乘")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is True
    assert result.evidence == "第 68 行的 QK^T 矩乘"
    assert judge_score(result) == 1.0


def test_verdict_value_takes_first_token(monkeypatch):
    """首 token 级 yes/no：`Verdict: Yes, because…` 的首 token 是 yes → yes。"""
    _patch(monkeypatch, "Verdict: Yes, because 两者都是先相乘再归一化")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is True


@pytest.mark.parametrize(
    "reply",
    [
        "Verdict: maybe",
        "Verdict: I think so",
        "",
        "这一段自由文本里没有任何 Verdict 行",
        "Verdict: no way",
        "Verdict:",
        "Verdict: 是",
        # 值级 yes 子串反例（R65）：取值里含 yes，但首 token 不是 yes。
        # 少了这三条，`_is_yes` 变异成 `"yes" in value.lower()` 能活过整套测试——
        # 真实后端回 `Verdict: 我觉得 yes` 时，首 token 实现正确判 False（fail-closed），
        # 子串实现会幻觉成 yes。这与 test_free_text_yes_is_not_accepted 守的
        # **整文本级** 是两个独立攻击面，两边都要有人看守，不许互相替代。
        "Verdict: not yes",
        "Verdict: 我觉得 yes",
        "Verdict: yesish",
    ],
)
def test_non_yes_no_answer_is_not_yes(monkeypatch, reply):
    """RF2：答非 yes-no 一律不是 yes——一旦兜底成 yes，整条对齐就是幻觉。

    `no way` 的首 token 是 no；空串 / 缺 Verdict 行 / 空值也都不是 yes。
    末三条是**值级**反例：Verdict 行的取值里含 yes 子串，但首 token 不是
    yes（not / 我觉得 / yesish）——它们把「取首 token」和「在值里搜子串」
    这两个实现区分开。
    """
    _patch(monkeypatch, reply)
    result = judge(_TERM, _SNIPPET)
    assert result.yes is False
    assert judge_score(result) == 0.0


def test_free_text_yes_is_not_accepted(monkeypatch):
    """绝不从自由文本里搜 yes——那就退回自由生成了（变异探针瞄的就是这条）。"""
    _patch(monkeypatch, "我觉得 yes 是对的，它们显然是同一个操作，没有别的话")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is False
    assert result.evidence == ""
    assert judge_score(result) == 0.0


@pytest.mark.parametrize(
    "reply",
    [
        "Verdict：yes",  # 全角冒号
        "verdict: YES",  # 键和值都大小写不敏感
        "   Verdict: yes   ",  # 行首行尾空白
        "Verdict: yes。",  # 值后面跟全角句号
        "前言一段\nVerdict: yes\nEvidence: 第 68 行的矩乘",  # Verdict 不在第一行
    ],
)
def test_verdict_line_tolerances(monkeypatch, reply):
    """R51 的容错边界：全角冒号、大小写、行首空白、值后标点、非首行。"""
    _patch(monkeypatch, reply)
    assert judge(_TERM, _SNIPPET).yes is True


def test_verdict_line_is_not_the_first_token_of_the_whole_reply(monkeypatch):
    """S19：不要对整个响应取首 token——那是 `Verdict:`，真实后端会全判失败。"""
    _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的矩乘")
    reply = judge_module.get_llm().chat("probe")
    assert reply.text.splitlines()[0].split()[0] == "Verdict:"
    # 而判据仍然必须判成 yes：证明取的是 Verdict 行赋值的首 token
    assert judge(_TERM, _SNIPPET).yes is True


def test_first_verdict_line_wins(monkeypatch):
    """出现多行 Verdict 时取第一行，后者不许翻案（可复现）。"""
    _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的矩乘\nVerdict: no")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is True


# --------------------------------------------------------------------------
# evidence 处理（R50 / R57）
# --------------------------------------------------------------------------


def test_evidence_is_stripped_of_surrounding_whitespace(monkeypatch):
    """R50：先 strip 外侧空白，再截断——顺序反了会留下 40 个空白字符。"""
    _patch(monkeypatch, "Verdict: yes\nEvidence:    第 68 行的 QK^T 矩乘   ")
    result = judge(_TERM, _SNIPPET)
    assert result.evidence == "第 68 行的 QK^T 矩乘"


def test_evidence_truncated_to_40_chars_not_bytes(monkeypatch):
    """R50：按字符数截断。中文 1 字 3 字节，按字节截断只剩 13 个汉字。"""
    long_evidence = "矩乘" * 60  # 120 个字符 = 360 字节
    _patch(monkeypatch, f"Verdict: yes\nEvidence: {long_evidence}")
    result = judge(_TERM, _SNIPPET)
    # 40 个字符 = 20 个「矩乘」；按字节截断只会留下 13 个汉字
    assert result.evidence == "矩乘" * 20
    assert len(result.evidence) == 40 == EVIDENCE_MAX_CHARS
    assert len(result.evidence.encode("utf-8")) == 120  # 40 字 = 120 字节
    assert len(long_evidence.encode("utf-8")) == 360


def test_evidence_exactly_40_chars_is_kept_whole(monkeypatch):
    """边界：刚好 40 个字符不被截断，41 个才截。"""
    backend = _patch(monkeypatch, "Verdict: yes\nEvidence: " + "甲" * 40)
    assert judge(_TERM, _SNIPPET).evidence == "甲" * 40
    backend.reply = "Verdict: yes\nEvidence: " + "甲" * 41
    assert judge(_TERM, _SNIPPET).evidence == "甲" * 40


def test_empty_evidence_forces_zero(monkeypatch):
    """RF2：模型没给依据 → evidence="" → judge_score 强制 0.0。"""
    _patch(monkeypatch, "Verdict: yes\nEvidence:")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is True
    assert result.evidence == ""
    assert judge_score(result) == 0.0


def test_missing_evidence_line_forces_zero(monkeypatch):
    """只有 Verdict 行、整行 Evidence 缺失 → 同样归零（依据必填）。"""
    _patch(monkeypatch, "Verdict: yes")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is True
    assert result.evidence == ""
    assert judge_score(result) == 0.0


def test_judge_score_rules():
    """R57：yes 且依据非空且非纯空白 → 1.0；其余一律 0.0。

    `""` 与 `"   "` 都强制 0.0；no 一律 0.0，不管有没有 evidence。
    """
    assert judge_score(JudgeResult(True, "第 68 行的 QK^T 矩乘")) == 1.0
    assert judge_score(JudgeResult(True, "")) == 0.0
    assert judge_score(JudgeResult(True, "   ")) == 0.0
    assert judge_score(JudgeResult(True, "\t\n ")) == 0.0
    assert judge_score(JudgeResult(False, "第 68 行的 QK^T 矩乘")) == 0.0
    assert judge_score(JudgeResult(False, "")) == 0.0


# --------------------------------------------------------------------------
# offline / 接口形状（R47 / R49 / R53）
# --------------------------------------------------------------------------


def test_offline_judge_scores_zero_with_reason(monkeypatch):
    """RF2 + R49：offline 必须诚实归零。

    注意分工：`JudgeResult` **没有 reason 字段**，所以这里只能断言
    `JudgeResult(False, "")` 与 `judge_score == 0.0`；那句给用户看的 reason
    由 S9 写进 unresolved / anchor，不是 judge 的职责。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    result = judge(_TERM, _SNIPPET)
    assert result == JudgeResult(False, "")
    assert result.yes is False
    assert result.evidence == ""
    assert judge_score(result) == 0.0
    assert JudgeResult._fields == ("yes", "evidence")


def test_llm_unavailable_from_chat_scores_zero(monkeypatch):
    """chat 抛 LLMUnavailable → 同样是 JudgeResult(False, "")，不兜底成 yes。"""
    monkeypatch.setattr(judge_module, "get_llm", lambda: UnavailableBackend())
    result = judge(_TERM, _SNIPPET)
    assert result == JudgeResult(False, "")
    assert judge_score(result) == 0.0


def test_judge_signature_has_no_mapping_param():
    """R47：签名里绝不允许出现 mapping: dict，也不许多一个出口字段。"""
    params = inspect.signature(judge).parameters
    assert "mapping" not in params
    assert list(params) == ["term", "snippet"]
    assert JudgeResult._fields == ("yes", "evidence")


def test_judge_reads_text_off_chat_result(monkeypatch):
    """R53：`get_llm().chat(...)` 返回 ChatResult 不是 str，必须取 `.text`。

    假后端交出去的是一个 ChatResult（且不是 str 子类）；直接对它做字符串
    操作的实现会在这里静默判错或抛 TypeError。
    """
    backend = _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的 QK^T 矩乘")
    result = judge(_TERM, _SNIPPET)
    handed_over = backend.replies[0]
    assert isinstance(handed_over, ChatResult)
    assert not isinstance(handed_over, str)
    assert handed_over.text == "Verdict: yes\nEvidence: 第 68 行的 QK^T 矩乘"
    assert result.yes is True
    assert result.evidence == "第 68 行的 QK^T 矩乘"


def test_judge_sends_the_built_prompt_to_the_backend(monkeypatch):
    """judge 必须用 judge_prompt 提问，且把 term 与 snippet 原样嵌进去。"""
    backend = _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的矩乘")
    judge(_TERM, _SNIPPET)
    assert backend.prompts == [judge_prompt(_TERM, _SNIPPET)]
    assert _TERM in backend.prompts[0]
    assert _SNIPPET in backend.prompts[0]


def test_judge_asks_once_per_call(monkeypatch):
    """一次判断题只问一次：多问一次就是在自由生成候选。"""
    backend = _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的矩乘")
    judge(_TERM, _SNIPPET)
    assert len(backend.prompts) == 1


def test_fake_backend_is_single_instance_across_calls(monkeypatch):
    """假后端必须单实例跨调用保持状态（控制器踩过：计数重置导致断言不触发）。"""
    backend = _patch(monkeypatch, "Verdict: yes\nEvidence: 第 68 行的矩乘")
    judge(_TERM, _SNIPPET)
    judge(_TERM, _SNIPPET)
    assert len(backend.prompts) == 2
    assert backend.prompts[0] == backend.prompts[1]


def test_judge_does_not_touch_embed(monkeypatch):
    """判断题只走 chat；偷偷调 embed 说明实现把检索和判断混在了一步里。"""
    _patch(monkeypatch, "Verdict: no\nEvidence: 看不出对应")
    result = judge(_TERM, _SNIPPET)
    assert result.yes is False
    assert judge_score(result) == 0.0
