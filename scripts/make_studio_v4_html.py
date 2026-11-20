"""用 index3.html 当模板，生成 paper-white 技术插图版画布 index4.html。

改造清单（与设计文档 2026-11-20-studio-canvas-v4-design.md 一一对应）：
1. 视觉：换掉宋体/印章/纸纹颗粒，改纸白 + 1px 墨线 + 极淡网格，卡片去投影；
2. 五类角色：每个节点右下角一枚小徽标（输入/处理/存储/转译/控制/非代码），
   系统层与子系统层卡片底部加一条五色微条（按文件占比）；
3. 图例：左下固定，五类色 + 两类边；
4. 选中节点后，右栏多一块「为什么归这一类」，列命中规则与原文；
5. 「按流水线排布」开关：默认关（自由力导向），打开后按五条带排布并画分区底。

跑法：python scripts/make_studio_v4_html.py
输入：docs/studio/mock/index3.html（模板）、docs/studio/mock/data4.json
输出：docs/studio/mock/index4.html
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOCK = ROOT / "docs" / "studio" / "mock"
TEMPLATE = MOCK / "index3.html"
DATA = MOCK / "data4.json"
OUT = MOCK / "index4.html"

STAGE_COLORS = {
    "io": "#2f6f8f",
    "process": "#4a5a6a",
    "storage": "#6b4f8a",
    "transform": "#a06a2c",
    "control": "#3f7a5a",
    "none": "#a8a8a8",
}
STAGE_NAMES = {
    "io": "输入输出", "process": "处理", "storage": "存储",
    "transform": "转译", "control": "控制", "none": "非代码",
}

CSS_OVERRIDE = """
/* ===== v4：纸白技术插图 ============================================
   去掉手账感的三样东西——宋体、印章、纸纹颗粒；换成论文插图那种
   「白底、墨线、等宽数字」的克制画法。五类流水线角色用低饱和色标。 */
:root, [data-theme="light"] {
  --serif: var(--sans);
  --bg: #f4f3ee;
  --panel: #ffffff;
  --panel-2: #f7f6f1;
  --line: #d8d5cc;
  --line-soft: #e9e6dc;
  --ink: #1b1e23;
  --ink-2: #52565c;
  --ink-3: #8c9096;
  --paper: #ffffff;
  --paper-hi: #ffffff;
  --grid: #e7e4da;
  --azure: #33507a;
  --flow: #9b3f2c;
  --grain: 0;
  --card: #ffffff;
  --card-hover: #fbfaf6;
  --sheet: 0 0 0 1px var(--line);
  --shadow: 0 0 0 1px var(--line);
  --st-io: #2f6f8f;
  --st-process: #4a5a6a;
  --st-storage: #6b4f8a;
  --st-transform: #a06a2c;
  --st-control: #3f7a5a;
  --st-none: #a8a8a8;
}
[data-theme="dark"] {
  --serif: var(--sans);
  --grain: 0;
  --sheet: 0 0 0 1px var(--line);
  --shadow: 0 0 0 1px var(--line);
  --st-io: #6fa8c4;
  --st-process: #9aa8b6;
  --st-storage: #a98cc4;
  --st-transform: #c9a06a;
  --st-control: #7bbd97;
  --st-none: #6e6e6e;
}

/* 入场动画 nodeIn 用 CSS transform 盖掉了 SVG 的 translate(x,y) 属性：
   动画没跑完时所有节点会堆在画布原点。技术插图不需要元素飞入，直接关掉。 */
.node, .node * { animation: none !important; }

/* 纸纹：body::before 是一层 multiply 混合的噪点，把整张画布压暗压暖，
   纸白技术插图要的是干净的白底，这层直接关掉。 */
body::before, .stage::after { display: none !important; }

/* 画布：去掉 index3 那层暖色暗角和纸黄渐变，只留极淡网格；纸白就该是纸白 */
.stage {
  background-color: var(--bg);
  background-image:
    linear-gradient(to right, color-mix(in srgb, var(--ink) 6%, transparent) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in srgb, var(--ink) 6%, transparent) 1px, transparent 1px);
  background-size: 24px 24px;
  box-shadow: none;
}
.top, .panel, .rail, .foot { background: var(--panel); }
.top { border-bottom: 1px solid var(--line); }
.panel { border-left: 1px solid var(--line); }
.rail { border-right: 1px solid var(--line); }
.foot { border-top: 1px solid var(--line); }
.grain, .stamp, .seal { display: none !important; }

/* 顶栏那个红底「笺」字是印章，手账的记号，换成中性墨块 */
.brand::before {
  content: ""; width: 16px; height: 16px; border-radius: 3px;
  background: var(--ink); color: transparent; box-shadow: none; font-size: 0;
}
.brand b { letter-spacing: .02em; }
/* import 依赖只留一条细虚线，不画箭头：它和数据流会走同一条路径，
   两个箭头叠在一起就成了画面中心那团红线；方向交给数据流箭头表达。 */
.edge.dep { marker-end: none; stroke-opacity: .55; }
.edge.dat { stroke-opacity: .9; }
.node .card { stroke: var(--line); stroke-width: 1; }
/* 卡片统一白底：index3 按 data-role 填米黄 tint，11 张叠起来整张画布就发黄，
   读起来像便签墙而不是技术插图。角色只留左侧色条 + 徽标。 */
g.node[data-role] rect.card { fill: #ffffff; }
.node rect.card { filter: none; }
.node:hover rect.card { stroke: var(--ink-3); }
.node .sheet { display: none; }
.node text.title, .node text.fname { font-family: var(--sans); letter-spacing: .01em; }
.node text.path, .node text.fdir, .node text.meta { font-family: var(--mono); }
.band { fill: color-mix(in srgb, var(--ink) 3%, transparent); stroke: none; }
.band-io { fill: color-mix(in srgb, var(--st-io) 7%, transparent); }
.band-process { fill: color-mix(in srgb, var(--st-process) 9%, transparent); }
.band-storage { fill: color-mix(in srgb, var(--st-storage) 7%, transparent); }
.band-transform { fill: color-mix(in srgb, var(--st-transform) 7%, transparent); }
.band-control { fill: color-mix(in srgb, var(--st-control) 8%, transparent); }
.band-none { fill: color-mix(in srgb, var(--st-none) 6%, transparent); }
.bandlabel { font: 600 11px/1 var(--sans); letter-spacing: .12em; fill: var(--ink-3); }
.node .stagebadge rect { opacity: .92; }
.node .stagetxt { font: 600 9.5px/1 var(--sans); fill: #fff; letter-spacing: .04em; }
.node.stage-none .stagebadge rect { opacity: .55; }
.stagebar { opacity: .9; }
.legend .st { display: inline-flex; align-items: center; gap: 5px; }
.legend .st i { width: 9px; height: 9px; border-radius: 2px; border: none; display: inline-block; }
.stagebox { margin-top: 14px; border-top: 1px solid var(--line-soft); padding-top: 10px; }
.stagebox .hd { font: 600 11px/1.4 var(--sans); letter-spacing: .08em; color: var(--ink-3); margin-bottom: 8px; }
.stagebox .row { display: flex; gap: 8px; align-items: baseline; margin: 5px 0; font: 12px/1.5 var(--sans); }
.stagebox .dot { width: 8px; height: 8px; border-radius: 2px; flex: none; transform: translateY(-1px); }
.stagebox .ev { color: var(--ink-2); font-family: var(--mono); font-size: 11px; }
.stagebox .note { color: var(--ink-3); font-size: 11px; margin-top: 8px; line-height: 1.5; }
.pipebtn.on { color: var(--ink); border-color: var(--ink-2); background: var(--panel-2); }
"""


def _js_constants() -> str:
    colors = json.dumps(STAGE_COLORS, ensure_ascii=False)
    names = json.dumps(STAGE_NAMES, ensure_ascii=False)
    return (
        "\n  var STAGE = %s;\n"
        "  var STAGE_NAME = %s;\n"
        '  var STAGE_LEVELS = { group: 1, sub: 1, file: 1 };\n'
        "  function stageOf(n) { return (n && n.stage) || 'none'; }\n"
        "  function stageColor(s) { return STAGE[s] || STAGE.none; }\n" % (colors, names)
    )


JS_FUNCS = r"""
  /* ---------- v4：流水线角色 ---------------------------------------- */
  function applyLayout(v) {
    v.nodes.forEach(function (n) {
      if (n._x === undefined) { n._x = n.x; n._y = n.y; }
      var on = state.pipeline && n.bx !== undefined;
      n.x = on ? n.bx : n._x;
      n.y = on ? n.by : n._y;
    });
  }

  function levelKey() {
    return state.level === "group" ? "group" : state.level === "sub" ? "sub" : null;
  }

  function bandLayer() {
    var key = levelKey(); if (!key) return null;
    var layers = DATA.layout_bands || {};
    return key === "sub" ? (layers.sub || {})[state.group] : layers[key];
  }

  function drawBands() {
    var L = bandLayer();
    if (!L) return;
    var g = el("g", { class: "bands" });
    (DATA.display_order || []).forEach(function (s) {
      var b = L.bands[s]; if (!b) return;
      g.appendChild(el("rect", { x: b.x + 6, y: 44, width: b.w, height: Math.max(120, L.height - 52), rx: 3, class: "band band-" + s }));
      g.appendChild(el("text", { x: b.x + 18, y: 32, class: "bandlabel" }, STAGE_NAME[s] || s));
    });
    vp.appendChild(g);
  }

  function stageWeights(n) {
    var out = [];
    (DATA.display_order || []).forEach(function (s) {
      var v = (n.stages || {})[s] || 0;
      if (v > 0) out.push([s, v]);
    });
    return out;
  }

  function drawStageBar(g, n, w, h) {
    var parts = stageWeights(n);
    var total = parts.reduce(function (a, p) { return a + p[1]; }, 0);
    if (!total || parts.length < 2) return;
    var x = 12, bw = w - 24, y = h - 4;
    var bar = el("g", { class: "stagebar" });
    parts.forEach(function (p) {
      var seg = Math.max(3, Math.round(bw * p[1] / total));
      bar.appendChild(el("rect", { x: x, y: y, width: seg, height: 3, rx: 1.5, fill: stageColor(p[0]) }));
      x += seg;
    });
    g.appendChild(bar);
  }

  function decorateStages(v) {
    Array.prototype.forEach.call(vp.querySelectorAll(".node"), function (g) {
      var id = g.getAttribute("data-id"), n = null;
      (v.nodes || []).forEach(function (x) { if (x.id === id) n = x; });
      if (!n) return;
      var s = stageOf(n);
      g.classList.add("stage-" + s);
      var card = g.querySelector("rect.card");
      var w = card ? +card.getAttribute("width") : (n.w || v.w);
      var h = card ? +card.getAttribute("height") : (n.h || v.h);
      var label = STAGE_NAME[s] || s;
      var bw = label.length * 10.5 + 12;
      var badge = el("g", { class: "stagebadge", transform: "translate(" + (w - bw - 7) + "," + (v.card === "file" ? 8 : 9) + ")" });
      badge.appendChild(el("rect", { x: 0, y: 0, width: bw, height: 15, rx: 2, fill: stageColor(s) }));
      badge.appendChild(el("text", { x: bw / 2, y: 10.8, "text-anchor": "middle", class: "stagetxt" }, label));
      g.appendChild(badge);
      if (v.card !== "file") drawStageBar(g, n, w, h);
    });
    /* 数据流上的「流动包」是 index3 的装饰，几条边叠在一个点上会糊成一团红线，
       技术插图不要它；边本身的箭头 marker 还在。 */
    var packs = vp.querySelector(".arrowtops");
    if (packs) packs.remove();
  }

  function injectStagePanel() {
    var body = document.getElementById("pBody"); if (!body) return;
    var n = null;
    (view().nodes || []).forEach(function (x) { if (x.id === state.sel) n = x; });
    if (!n) return;
    var s = stageOf(n);
    var box = document.createElement("div");
    box.className = "stagebox";
    var html = '<div class="hd">流水线角色</div>'
      + '<div class="row"><span class="dot" style="background:' + stageColor(s) + '"></span><b>' + (STAGE_NAME[s] || s) + '</b>'
      + '<span class="ev">' + (DATA.meta_stage_note || "") + '</span></div>';

    var ev = n.stage_evidence || {};
    var keys = Object.keys(ev);
    if (keys.length) {
      keys.forEach(function (k) {
        ev[k].forEach(function (e) {
          var kind = e.kind === "import" ? "import" : e.kind === "path" ? "路径" : "符号";
          html += '<div class="row"><span class="dot" style="background:' + stageColor(k) + ';opacity:.55"></span>'
            + '<span class="ev">' + kind + ' 命中 ' + e.hits.join("、") + '</span></div>';
        });
      });
    } else if (n.stages) {
      var parts = stageWeights(n);
      var total = parts.reduce(function (a, p) { return a + p[1]; }, 0) || 1;
      parts.forEach(function (p) {
        html += '<div class="row"><span class="dot" style="background:' + stageColor(p[0]) + '"></span>'
          + '<b>' + (STAGE_NAME[p[0]] || p[0]) + '</b><span class="ev">' + p[1] + ' 个文件 · ' + Math.round(p[1] * 100 / total) + '%</span></div>';
      });
      html += '<div class="note">目录层的占比是它下面所有文件按单文件角色汇总的结果。</div>';
    }
    html += '<div class="note">' + (DATA.stage_weight_note || "") + '；`node:fs` 这类到处都有的 import 不计分，避免把一半文件误判。</div>';
    box.innerHTML = html;
    body.appendChild(box);
  }
"""


COUNT_OLD = """  (function countUp() {
    var ns = document.querySelectorAll(".stat b[data-n]");
    Array.prototype.forEach.call(ns, function (n) {
      var to = +n.getAttribute("data-n"), t0 = performance.now();
      function step(t) {
        var k = Math.min(1, (t - t0) / 700), e = 1 - Math.pow(1 - k, 3);
        n.textContent = fmt(Math.round(to * e));
        if (k < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  })();"""

COUNT_NEW = """  // v4：顶部数字直接到位，不做 700ms 滚动——首屏就该是准数
  (function countUp() {
    var ns = document.querySelectorAll(".stat b[data-n]");
    Array.prototype.forEach.call(ns, function (n) {
      n.textContent = fmt(+n.getAttribute("data-n"));
    });
  })();"""


def patch(html: str) -> str:
    def once(old: str, new: str, label: str) -> str:
        assert html.count(old) == 1, "锚点 %s 命中 %d 次" % (label, html.count(old))
        return html.replace(old, new, 1)

    # 0) 顶栏加「按流水线排布」按钮
    html = once(
        '  <button class="iconbtn" id="themeBtn"',
        '  <button class="btn pipebtn" id="pipeBtn" title="按五类流水线排布">按流水线排布</button>\n'
        '  <button class="iconbtn" id="themeBtn"',
        "pipeBtn",
    )

    # 1) 图例换成五类 + 两类边
    legend = re.search(r'<div class="legend">.*?</div>', html, re.S)
    assert legend, "legend"
    stages = "".join(
        '<span class="st"><i style="background:%s"></i>%s</span>' % (color, STAGE_NAMES[key])
        for key, color in STAGE_COLORS.items() if key != "none"
    )
    html = html[: legend.start()] + (
        '<div class="legend">' + stages +
        '<span style="opacity:.35">|</span>'
        '<span><i class="dep"></i>import 依赖</span>'
        '<span id="lgFlow" class="toggle"><i class="dat"></i>数据流</span>'
        '<span><i class="live"></i>选中即点亮</span>'
        '</div>'
    ) + html[legend.end():]

    # 1.5) 纸白是默认主题：系统深色时 auto 会走深色，和「纸白技术插图」冲突
    html = once('<html lang="zh-CN" data-theme="auto">', '<html lang="zh-CN" data-theme="light">', "theme-html")
    html = once('theme: "auto"', 'theme: "light"', "theme-state")

    # 2) CSS 覆盖
    html = once("</style>", CSS_OVERRIDE + "\n</style>", "style")

    # 3) STAGE 常量
    m = re.search(r'var ROLE_NAME = \{[^}]*\};', html)
    assert m, "ROLE_NAME"
    html = html[: m.end()] + _js_constants() + html[m.end():]

    # 4) 新函数插到 render 之前
    html = once("  function render() {", JS_FUNCS + "\n  function render() {", "render")

    # 5) state 加 pipeline
    html = once('showFlow: true };', 'showFlow: true, pipeline: false };', "state")

    # 6) render 里：应用布局 + 画分区带
    html = once(
        "    var v = view(), byId = {};\n",
        "    var v = view(), byId = {};\n    applyLayout(v);\n",
        "applyLayout",
    )
    html = once(
        '    vp.textContent = "";',
        '    vp.textContent = "";\n    if (state.pipeline) drawBands();',
        "bands",
    )

    # 7) 节点画完后加徽标与微条
    html = once("    vp.appendChild(gN);\n", "    vp.appendChild(gN);\n    decorateStages(v);\n", "decorate")

    # 8) 选中后补一块角色证据
    html = once("    paintPanel();\n  }", "    paintPanel();\n    injectStagePanel();\n  }", "injectPanel")

    # 8.1) 数据流边收细：index3 的 2.6+min(4.2,…) 在 73% 缩放下糊成一条粗带
    html = once("function (c) { return 2.6 + Math.min(4.2, Math.log1p(c) * 1.9); }",
                "function (c) { return 1.5 + Math.min(2.4, Math.log1p(c) * 1.2); }", "dat-edge-width")

    # 8.2) 中文摘要按真实字宽换行：index3 按 6.6px/字估算（西文宽度），
    #      汉字实际约 12px，中文 summary 会溢出卡片右侧压到隔壁卡片上。
    wrap_old = 'wrap(n.summary.text, Math.floor((w - 32) / 6.6))'
    assert html.count(wrap_old) == 2, "wrap 锚点应该正好两处，实际 %d" % html.count(wrap_old)
    html = html.replace(wrap_old, 'wrap(n.summary.text, Math.floor((w - 32) / 11.8))')

    # 8.5) 顶部数字直接到位
    html = once(COUNT_OLD, COUNT_NEW, "countUp")

    # 9) 按钮接线
    html = once(
        '  document.getElementById("zIn").onclick',
        '  document.getElementById("pipeBtn").onclick = function () {\n'
        '    state.pipeline = !state.pipeline;\n'
        '    this.classList.toggle("on", state.pipeline);\n'
        '    this.textContent = state.pipeline ? "自由排布" : "按流水线排布";\n'
        '    render(); fit();\n'
        '  };\n'
        '  document.getElementById("zIn").onclick',
        "pipeBtn-onclick",
    )
    return html


def main() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    data = DATA.read_text(encoding="utf-8")

    # 替换内嵌 DATA：从 "DATA = " 后的 { 开始，按 JSON 语法吃到匹配的 }
    marker = html.index("DATA = ")
    start = html.index("{", marker)
    _, end = json.JSONDecoder().raw_decode(html[start:])
    html = html[:start] + data + html[start + end:]

    html = patch(html)
    OUT.write_text(html, encoding="utf-8")
    print("写出:", OUT.relative_to(ROOT), "%.1f KB" % (OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
