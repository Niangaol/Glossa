"""把 SafeTrace 的 Studio 原型数据升到 v4：给每个文件打「流水线角色」，并算分带布局。

产物（都在 docs/studio/mock/）：
- data4.json   原 data.json 不动，只加字段：文件级 stage / stage_evidence / stage_score，
               分组级 stages / stage，以及 layout_bands（五列分区带的坐标）；
- index4.html  由 index3.html 当模板改造出来的「纸白技术插图」版画布。

跑法：python scripts/build_studio_v4.py

分类规则（设计文档 §3，页面上原样展示命中证据）：
    控制    符号含 orchestrat/scheduler/statemachine/queue/daemon/pipeline/worker/taskgraph
            或 import 含 orchestrat/statemachine/taskgraph/scheduler/worker_threads
            或路径含 orchestrator/daemon/runtime/scheduler/statemachine/taskgraph
    转译    import 含 parser/compiler/babel/esbuild/markdown/schema/vite/postcss
            或符号含 parse/compile/transpile/render/format/normalize/convert/markdown
    存储    import 含 sqlite/better-sqlite3/pg/mysql/redis/lancedb/leveldb
            或符号含 store/db/save/persist/backup/repository/dao/migrat
    输入输出 import 含 http/ws/fetch/axios/express/fastify/hono/koa/node:net
            或路径含 gateway/api//server/client/cli/ingest/web//views/routes/handler
            或符号含 handler/route/fetch/request/response/socket/listen/stream
    处理    代码文件兜底：四类都没命中，但它确实是源码
    非代码   md/json/yaml/css 这类不参与流程判定，记 none（页面上显示「—」，不计进占比）

打分而不是纯命中：路径命中 3 分、import 命中 2 分、符号命中 1 分，取最高分那一类。
理由：路径是仓库作者自己放的位置，最可信；import 次之；符号名最容易误伤。
`node:fs` 故意不算进任何一类——几乎每个脚本都摸文件系统，算进去会把一半文件误标成存储/输入。
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOCK = ROOT / "docs" / "studio" / "mock"
DATA = MOCK / "data.json"
OUT_DATA = MOCK / "data4.json"

# 判定优先级（同分时靠前者赢）
PRIORITY = ("control", "transform", "storage", "io", "process")
# 画布从左到右：数据怎么走，就按输入 → 处理 → 存储 → 转译 → 控制排
DISPLAY_ORDER = ("io", "process", "storage", "transform", "control", "none")
STAGE_LABEL = {
    "io": "输入输出",
    "process": "处理",
    "storage": "存储",
    "transform": "转译",
    "control": "控制",
    "none": "非代码",
}
WEIGHT = {"path": 3, "import": 2, "symbol": 1}
COLW = {"group": 460, "sub": 420, "file": 340}
CODE_LANGS = {
    "typescript", "javascript", "vue", "python", "shell", "tsx", "jsx",
    "c", "cpp", "csharp", "java", "go", "rust", "ruby", "php", "swift", "kotlin",
}

RULES = {
    "control": {
        "import": ("orchestrat", "scheduler", "statemachine", "state-machine", "taskgraph", "worker_threads"),
        "path": ("orchestrator", "daemon", "runtime", "scheduler", "statemachine", "taskgraph"),
        "symbol": ("orchestrat", "scheduler", "statemachine", "queue", "daemon", "pipeline", "worker", "taskgraph"),
    },
    "transform": {
        "import": ("parser", "compiler", "babel", "esbuild", "markdown", "schema", "vite", "postcss"),
        "path": (),
        "symbol": ("parse", "compile", "transpile", "render", "format", "normalize", "convert", "markdown"),
    },
    "storage": {
        "import": ("sqlite", "better-sqlite3", " pg", "mysql", "redis", "lancedb", "leveldb"),
        "path": (),
        "symbol": ("store", "db", "save", "persist", "backup", "repository", "dao", "migrat"),
    },
    "io": {
        "import": ("http", " ws", "fetch", "axios", "express", "fastify", "hono", "koa", "node:net"),
        "path": ("gateway", "api/", "server", "client", "cli", "ingest", "web/", "views", "routes", "handler"),
        "symbol": ("handler", "route", "fetch", "request", "response", "socket", "listen", "stream"),
    },
}


def _hits(needles, text: str) -> list[str]:
    low = text.lower()
    return [n.strip() for n in needles if n.strip() and n.strip() in low]


def classify(lang: str, path: str, imports: list[dict], symbols: list[dict]) -> tuple[str, dict, dict]:
    """返回 (stage, evidence, score)。非代码文件直接 none。"""
    if (lang or "").lower() not in CODE_LANGS:
        return "none", {}, {}

    spec = " ".join(str(i.get("specifier") or "") for i in imports)
    sym = " ".join(str(s.get("name") or "") for s in symbols)
    score: dict[str, int] = {}
    evidence: dict[str, list[dict]] = {}

    for stage in ("control", "transform", "storage", "io"):
        rule = RULES[stage]
        found: list[dict] = []
        total = 0
        for kind, needles, corpus in (
            ("import", rule["import"], spec),
            ("path", rule["path"], path),
            ("symbol", rule["symbol"], sym),
        ):
            hit = _hits(needles, corpus)
            if hit:
                found.append({"kind": kind, "hits": hit[:4]})
                total += WEIGHT[kind]
        if found:
            evidence[stage] = found
            score[stage] = total

    if not score:
        return "process", {}, {"process": 0}
    best = max(PRIORITY[:-1], key=lambda k: (score.get(k, 0), -PRIORITY.index(k)))
    return best, evidence, score


def band_layout(nodes: list[dict], colw: int, gap: int, top: int = 96) -> dict:
    """按 stage 分列排布：空列只留一条窄槽，有内容的列按实际卡片宽度给位。

    固定 5×448 的初版算出来 2760 宽，缩到 0.42 之后字小到看不清；
    事实上组级只有「输入输出/处理/非代码」三列有东西，空列不该占满宽。
    """
    cols = {s: [] for s in DISPLAY_ORDER}
    for n in nodes:
        cols.setdefault(n.get("stage") or "none", []).append(n)

    EMPTY_W = 64
    MAX_ROWS = 4           # 一列最多堆 3 行，再多就并一列，别把画布拉成一条竖线
    widths, heights = {}, {}
    for stage in DISPLAY_ORDER:
        item = cols.get(stage) or []
        if not item:
            widths[stage], heights[stage] = EMPTY_W, top
            continue
        card = max((n.get("w") or colw - 30) for n in item)
        subcols = max(1, -(-len(item) // MAX_ROWS))
        widths[stage] = subcols * (card + 28) + 8
        heights[stage] = top + min(len(item), MAX_ROWS) * ((item[0].get("h") or 80) + gap)

    bands, x, deepest = {}, 0, top
    for stage in DISPLAY_ORDER:
        w = widths[stage]
        item = sorted(cols.get(stage) or [], key=lambda m: (-(m.get("w") or 0), str(m.get("label"))))
        for idx, n in enumerate(item):
            row, sub = idx % MAX_ROWS, idx // MAX_ROWS
            n["bx"] = x + 14 + sub * ((n.get("w") or colw - 30) + 28)
            n["by"] = top + row * ((n.get("h") or 80) + gap)
        bands[stage] = {"x": x, "w": w - 8, "empty": not item}
        deepest = max(deepest, heights[stage])
        x += w
    return {"bands": bands, "width": x, "height": deepest}


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    details = data["details"]

    classified: dict[str, dict] = {}
    for path, row in details.items():
        stage, evidence, score = classify(path=path, lang=row.get("lang") or "",
                                          imports=row.get("imports") or [],
                                          symbols=row.get("symbols") or [])
        classified[path] = {"stage": stage, "stage_evidence": evidence, "stage_score": score}

    def agg_for(prefix: str) -> dict:
        out = {k: 0 for k in DISPLAY_ORDER}
        for path, info in classified.items():
            if not prefix:
                if "/" in path:
                    continue
            elif not (path == prefix or path.startswith(prefix + "/")):
                continue
            out[info["stage"]] += 1
        return out

    def dominant(stages: dict) -> str:
        code = {k: v for k, v in stages.items() if k != "none"}
        if not any(code.values()):
            return "none"
        return max(DISPLAY_ORDER[:-1], key=lambda k: (code.get(k, 0), -DISPLAY_ORDER.index(k)))

    for group in data["groups"]:
        group.setdefault("w", 320)
        group.setdefault("h", 168)
        group["stages"] = agg_for((group.get("path") or "").rstrip("/"))
        group["stage"] = dominant(group["stages"])

    for bucket in data["subs"].values():
        for node in bucket.get("nodes") or []:
            node.setdefault("w", 320)
            node.setdefault("h", 164)
            prefix = (node.get("prefix") or "").rstrip("/")
            node["stages"] = agg_for(prefix)
            node["stage"] = dominant(node["stages"])

    for bucket in data["files"].values():
        for node in bucket.get("nodes") or []:
            node.setdefault("w", 300)
            node.setdefault("h", 74)
            info = classified.get(node.get("path"))
            if info:
                node["stage"] = info["stage"]
                node["stage_evidence"] = info["stage_evidence"]
                node["stage_score"] = info["stage_score"]
            else:
                node["stage"] = "none"

    # 组级一套；子系统级一套一个（每次只显示一个组的模块）；文件层不分带——
    # 文件一次只显示几十个、卡片小，分带只会把画布拉成 13000 宽。
    layout = {
        "group": band_layout(data["groups"], COLW["group"], 34),
        "sub": {gk: band_layout(bucket.get("nodes") or [], COLW["sub"], 26)
                for gk, bucket in data["subs"].items()},
    }

    data["layout_bands"] = layout
    data["display_order"] = list(DISPLAY_ORDER)
    data["stage_labels"] = STAGE_LABEL
    data["stage_weight_note"] = "路径命中 3 分 · import 命中 2 分 · 符号命中 1 分"
    data["meta_stage_note"] = "角色由 import、路径与符号名推断，不是运行时观测"
    OUT_DATA.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tally = {k: 0 for k in DISPLAY_ORDER}
    for info in classified.values():
        tally[info["stage"]] += 1
    print("文件数:", len(classified))
    for stage in DISPLAY_ORDER:
        print("  %-10s %4d" % (STAGE_LABEL[stage], tally[stage]))
    print("\n分组主类：")
    for group in data["groups"]:
        code = {k: v for k, v in group["stages"].items() if k != "none"}
        top = sorted(code.items(), key=lambda kv: -kv[1])[:3]
        print("  %-10s %-8s %s" % (group["label"], STAGE_LABEL[group["stage"]],
                                   " · ".join("%s %d" % (STAGE_LABEL[k], v) for k, v in top if v)))
    print("\n写出:", OUT_DATA.relative_to(ROOT))


if __name__ == "__main__":
    main()
