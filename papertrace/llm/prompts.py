"""提示词常量。

铁律：**初次（L0–L2 的判断题）与深钻（L3）必须是两个常量，禁止混用。**
混用会让深钻丢掉父节点结论，退化成「再问一遍」，L3 的三项验证就白做了。

JUDGE_PROMPT / DRILL_PROMPT 各自冻结（改任一条都要同时升 JUDGE_PROMPT_VERSION
或在深钻侧单独记版本）；prompt 版本与 prompt 本身必须是两个可分别演进的东西。
"""

from __future__ import annotations

JUDGE_PROMPT = """你是论文与代码的对账员。给你一个论文公式项和一段代码，判断它们是不是同一件事。

规则：
1. 只能回答 yes / no。不要解释映射关系，不要列出多个候选。
2. 回答 yes 时必须给依据：一句中文，不超过 40 字，必须指向代码里的具体操作。
3. 拿不准就回答 no。误连一条线比漏连一条线更糟。

输出格式（严格两行）：
Verdict: yes|no
Evidence: <≤40 字的依据>
"""

#: R48：冻结。prompt 一改就要能对回是哪一版，否则历史判定不可复现。
JUDGE_PROMPT_VERSION = "judge-v1"


def judge_prompt(term_text: str, snippet: str) -> str:
    """R48：冻结的 JUDGE_PROMPT 原文 + 一段固定格式的输入区。

    输入区只是把两个入参原样嵌进去，不再写任何规则或输出格式——
    那会让同一个问题有两套指令，模型该听哪套就没准了。
    """
    return f"{JUDGE_PROMPT}\n论文公式项：\n{term_text}\n\n代码片段：\n{snippet}\n"


DRILL_PROMPT = """你在做一次深钻核对。已知父节点结论为：{parent_claim}

现在要核对的子问题是：{question}

规则：
1. 先复述父节点结论，再判断它在当前节点上是否仍然成立。
2. 不成立时必须给出反例（具体数值、形状或代码行），不接受「可能不成立」。
3. 不能顺着父节点结论往下推；父节点可能是错的。
4. 输出三段：Probe（实测）/ Equivalent（符号等价）/ Adversarial（你自己的反驳），缺任何一段都视为无效回答。
"""
