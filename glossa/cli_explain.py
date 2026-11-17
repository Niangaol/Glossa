"""A6：explain 的 AI 路径（--ai / --llm fake|openai）与它的 argparse 选项。

放在这里而不是 cli.py：那边贴着 200 行上限（R452 同尺）。这里只回答三件事——
「这次要不要走 AI」（wanted）、「AI 用哪个后端」（kind）、「结果写到哪、印一行什么」（run）。
既有裸 --llm 那条模型块路径原样留在 cli.py，输出逐字不变。

退出码与既有约定一致：--ai 但没有可用后端是 4（绝不静默退回程序版）；AI 页面组装失败是 2。
"""

from __future__ import annotations

import pathlib

from glossa import cli_facts
from glossa.explain import ai_pipeline, llm_config, styles
from papertrace.exceptions import BuildError, LLMUnavailable
from papertrace.exit_codes import MISSING_RUNTIME

KINDS = ("fake", "openai", "ollama")   #: --llm 的两个 AI 路径取值；裸 --llm 仍走旧路径
CHOICES = ("fake", "openai", "ollama", "offline")   # R510：argparse 直接挡掉拼错的值
OK = 0
AI_FAIL = cli_facts.BUILD_FAIL         # 2：AI 页面组装失败（含体积超限）
NO_RUNTIME = MISSING_RUNTIME           # 4：没有可用后端 / 配了但连不上


def add_options(parser):
    """三个新选项。--llm 用 nargs="?"：裸 --llm 仍是 True，旧路径一个字都不用改。"""
    parser.add_argument("--ai", action="store_true",
                        help="用 AI 分节撰写整页（每节过五道内容闸；没有后端时 exit 4）")
    parser.add_argument("--llm", nargs="?", const=True, default=None, choices=CHOICES,
                        metavar="fake|openai|ollama|offline",
                        help="模型后端：fake 是离线桩（不联网，页头标注）；ollama 尚未实现；"
                             "裸 --llm 保持原来的模型块路径")
    parser.add_argument("--style", choices=styles.style_names(), default="magazine",
                        help="AI 页的风格预设（magazine / report / cards，默认 magazine）")
    return parser


def wanted(args) -> bool:
    """--ai，或 --llm 给了 fake/openai（这两个值隐含 --ai）；裸 --llm 不算。"""
    return bool(getattr(args, "ai", False)) or getattr(args, "llm", None) in KINDS


def kind(args) -> str:
    """显式 --llm fake 才用桩；--llm ollama 是本地后端；--ai 或 --llm openai 走真后端。"""
    value = getattr(args, "llm", None)
    return value if value in KINDS else "openai"


def bad(args):
    """R510：裸 --llm 与 offline 不能和 --ai 一起用；其余非法取值 argparse 已经挡掉。"""
    value = getattr(args, "llm", None)
    if value is None or value in KINDS:       # 没给 / fake / openai / ollama 都合法
        return None
    if value is True:
        return ("glossa explain：--ai 需要明确指定后端，裸 --llm 不算；"
                "请写 --ai --llm fake 或 --ai --llm openai。")
    return ("glossa explain：--ai 不能和 --llm %r 一起用；--llm 只接受 %s。"
            % (value, " / ".join(CHOICES)))


def run(args, doc):
    """一整页 AI 讲解：建后端 → run_ai → 写 <out>/explain.html → 一行摘要。"""
    message = bad(args)
    if message:
        return cli_facts.fail(AI_FAIL, message)
    name = kind(args)
    if name == "ollama":                          # R510：本地后端还没实现，响亮报 4
        return cli_facts.fail(NO_RUNTIME, "glossa explain：--llm ollama 是本地后端，"
                              "papertrace 尚未实现；请用 --llm fake 或 --llm openai。")
    if name != "fake":
        try:
            cfg = llm_config.resolve()            # A1：配置只读这一处
        except ValueError as exc:                 # backend 写错：报原文，不吞成 traceback
            return cli_facts.fail(NO_RUNTIME, "glossa explain：AI 配置不合法：%s" % exc)
        if not llm_config.ready(cfg):
            return cli_facts.fail(NO_RUNTIME,
                                  "glossa explain：--ai 需要可用的模型后端：%s"
                                  "；先用 --llm fake 离线跑通。" % llm_config.describe(cfg))
    try:
        result = ai_pipeline.run_ai(doc, ai_pipeline.build_llm(name), args.style,
                                    root=pathlib.Path(args.repo))
    except LLMUnavailable as exc:                 # 配了但连不上：仍是 4，绝不静默降级
        return cli_facts.fail(NO_RUNTIME, "glossa explain：模型后端不可用：%s" % exc)
    except BuildError as exc:                     # 含分节解析失败、体积超限
        return cli_facts.fail(AI_FAIL, "glossa explain：AI 讲解页生成失败：%s" % exc)
    path = ai_pipeline.write_page(result["html"], args.out)
    print("讲解页：%s · %d 节 · 未溯源 %d 处%s"
          % (path, len(result["sections"]), result["untraced"],
             " · " + result["deviation"] if result["deviation"] else ""))
    return OK
