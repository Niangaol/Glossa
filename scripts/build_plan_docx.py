# -*- coding: utf-8 -*-
"""Generate PaperTrace engineering plan Word document."""
from pathlib import Path
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsmap
from docx.shared import Cm, Emu, Inches, Pt, RGBColor

ROOT = Path(r"D:\AgentPrograms\PaperTrace")
OUT = ROOT / "PaperTrace_工程落地计划书.docx"
FIG = ROOT / "docs" / "figures"
NAVY = RGBColor(0x1F, 0x4E, 0x79)
NAVY_TUPLE = (0x1F, 0x4E, 0x79)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x5C, 0x5C, 0x5C)
RED = RGBColor(0xA1, 0x26, 0x26)
GREEN = RGBColor(0x02, 0x7A, 0x48)
ORANGE = RGBColor(0xB5, 0x47, 0x08)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_FILL = "1F4E79"
ROW_ALT = "F4F7FB"
WARN_FILL = "FDECEC"
OK_FILL = "EAF6EF"
EAST = "微软雅黑"
ASCII = "Calibri"
MONO = "Consolas"
# content width 16.0cm; page 21.0 minus 2.4+2.4 margins = 16.2cm
CONTENT_TWIPS = 9072


def set_run_font(run, size=None, bold=None, color=None, italic=None):
    run.font.name = ASCII
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ASCII)
    rFonts.set(qn("w:hAnsi"), ASCII)
    rFonts.set(qn("w:eastAsia"), EAST)
    rFonts.set(qn("w:cs"), ASCII)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade_cell(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def set_cell_borders(cell, color="C5CDD6", sz="4"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcBorders")):
        tcPr.remove(old)
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), sz)
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tcPr.append(borders)


def set_cell_margins(cell, top=60, bottom=60, left=80, right=80):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for name, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{name}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def prevent_row_split(row):
    tr = row._tr
    trPr = tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    trPr.append(cant)


def set_style_font(style, size, bold=False, color=None, before=0, after=8, line=1.15):
    font = style.font
    font.name = ASCII
    font.size = Pt(size)
    font.bold = bold
    if color is not None:
        font.color.rgb = color
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ASCII)
    rFonts.set(qn("w:hAnsi"), ASCII)
    rFonts.set(qn("w:eastAsia"), EAST)
    pf = style.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def configure_styles(doc):
    normal = doc.styles["Normal"]
    set_style_font(normal, 11, before=0, after=8, line=1.2)
    pf = normal.paragraph_format
    pf.widow_control = True
    set_style_font(doc.styles["Title"], 26, bold=True, color=NAVY, before=0, after=6, line=1.15)
    set_style_font(doc.styles["Subtitle"], 14, color=MUTED, before=0, after=12, line=1.15)
    set_style_font(doc.styles["Heading 1"], 16, bold=True, color=NAVY, before=14, after=6, line=1.15)
    set_style_font(doc.styles["Heading 2"], 13, bold=True, color=NAVY, before=12, after=4, line=1.15)
    set_style_font(doc.styles["Heading 3"], 12, bold=True, color=RGBColor(0x2E, 0x5A, 0x88), before=10, after=4, line=1.15)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        pPr = doc.styles[name].element.get_or_add_pPr()
        keep = OxmlElement("w:keepNext")
        pPr.append(keep)


def set_page(doc):
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.4)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.2)
    sec.header_distance = Cm(1.0)
    sec.footer_distance = Cm(1.0)


def add_header_footer(doc):
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = hp.add_run("PaperTrace  ·  工程落地计划书  ·  v1.1")
    set_run_font(r, 9, color=MUTED)
    hp.paragraph_format.space_after = Pt(2)
    # bottom border on header
    pPr = hp._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), "1F4E79")
    pBdr.append(bottom)
    pPr.append(pBdr)

    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = fp.add_run("基于规格书 v1.0 修订  ·  2026-11-14  ·  第 ")
    set_run_font(r1, 9, color=MUTED)
    # PAGE field
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    r_page = fp.add_run()
    set_run_font(r_page, 9, color=MUTED)
    r_page._r.append(fld1)
    r_page._r.append(instr)
    r_page._r.append(fld2)
    r2 = fp.add_run(" 页")
    set_run_font(r2, 9, color=MUTED)


def p(doc, text, *, size=11, bold=False, color=INK, align=None, space_after=8, space_before=0, italic=False, keep=False):
    para = doc.add_paragraph()
    if align is not None:
        para.alignment = align
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    para.paragraph_format.line_spacing = 1.2
    run = para.add_run(text)
    set_run_font(run, size=size, bold=bold, color=color, italic=italic)
    if keep:
        keep_with_next(para)
    return para


def add_runs(para, parts):
    """parts: list of (text, kwargs)"""
    for text, kw in parts:
        run = para.add_run(text)
        set_run_font(run, **kw)
    return para


def rich(doc, parts, *, align=None, space_after=8, space_before=0):
    para = doc.add_paragraph()
    if align is not None:
        para.alignment = align
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    para.paragraph_format.line_spacing = 1.2
    for text, kw in parts:
        run = para.add_run(text)
        set_run_font(run, **kw)
    return para


def keep_with_next(para):
    pPr = para._p.get_or_add_pPr()
    if pPr.find(qn("w:keepNext")) is None:
        pPr.append(OxmlElement("w:keepNext"))
    return para


def h1(doc, text):
    para = doc.add_heading(text, level=1)
    for run in para.runs:
        set_run_font(run, size=16, bold=True, color=NAVY)
    return keep_with_next(para)


def h2(doc, text):
    para = doc.add_heading(text, level=2)
    for run in para.runs:
        set_run_font(run, size=13, bold=True, color=NAVY)
    return keep_with_next(para)


def h3(doc, text):
    para = doc.add_heading(text, level=3)
    for run in para.runs:
        set_run_font(run, size=12, bold=True, color=RGBColor(0x2E, 0x5A, 0x88))
    return keep_with_next(para)


def bullet(doc, text, level=0):
    para = doc.add_paragraph(style="List Bullet")
    para.clear()
    para.paragraph_format.left_indent = Cm(0.75 + 0.5 * level)
    para.paragraph_format.space_after = Pt(3)
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.line_spacing = 1.15
    run = para.add_run(text)
    set_run_font(run, size=11, color=INK)
    return para


def caption(doc, text):
    para = p(doc, text, size=9, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12, space_before=2, italic=True)
    return para


def add_picture(doc, name, width_cm=15.8):
    path = FIG / name
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(6)
    para.paragraph_format.space_after = Pt(2)
    run = para.add_run()
    run.add_picture(str(path), width=Cm(width_cm))
    return para


def set_tbl_width(table, total=CONTENT_TWIPS, col_widths=None):
    """Force fixed layout. python-docx already inserts tblW=auto; overwrite it."""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    existing_w = tblPr.find(qn("w:tblW"))
    if existing_w is None:
        existing_w = OxmlElement("w:tblW")
        tblPr.append(existing_w)
    existing_w.set(qn("w:w"), str(total))
    existing_w.set(qn("w:type"), "dxa")
    layout = tblPr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tblPr.append(layout)
    layout.set(qn("w:type"), "fixed")
    if col_widths is None:
        n = len(table.columns)
        wts = [total // n] * n
        wts[-1] = total - sum(wts[:-1])
    else:
        s = sum(col_widths)
        wts = [int(total * w / s) for w in col_widths]
        wts[-1] = total - sum(wts[:-1])
    grid = tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for i, gc in enumerate(list(grid)):
            if i < len(wts):
                gc.set(qn("w:w"), str(wts[i]))
    return wts


def keep_table_together(table):
    tbl = table._tbl
    for tr in tbl.findall(qn("w:tr")):
        trPr = tr.find(qn("w:trPr"))
        if trPr is None:
            trPr = OxmlElement("w:trPr")
            tr.insert(0, trPr)
        if trPr.find(qn("w:cantSplit")) is None:
            trPr.append(OxmlElement("w:cantSplit"))


def make_table(doc, headers, rows, col_widths=None, header_fill=HEADER_FILL):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    wts = set_tbl_width(table, CONTENT_TWIPS, col_widths)

    def fill_row(row, values, *, header=False, alt=False, warn=False):
        prevent_row_split(row)
        for i, (cell, val) in enumerate(zip(row.cells, values)):
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_before = Pt(2)
            para.paragraph_format.space_after = Pt(2)
            para.paragraph_format.line_spacing = 1.1
            run = para.add_run(str(val))
            if header:
                set_run_font(run, size=10, bold=True, color=WHITE)
                shade_cell(cell, header_fill)
            else:
                set_run_font(run, size=10, color=INK)
                if warn:
                    shade_cell(cell, WARN_FILL)
                elif alt:
                    shade_cell(cell, ROW_ALT)
                else:
                    shade_cell(cell, "FFFFFF")
            set_cell_borders(cell)
            set_cell_margins(cell)
            # cell width
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            tcW = OxmlElement("w:tcW")
            tcW.set(qn("w:w"), str(wts[i]))
            tcW.set(qn("w:type"), "dxa")
            tcPr.append(tcW)

    fill_row(table.rows[0], headers, header=True)
    for ri, row_vals in enumerate(rows):
        fill_row(table.rows[ri + 1], row_vals, alt=(ri % 2 == 1))
    # keep header with first body row so a heading+header cannot sit alone at page bottom
    if len(table.rows) >= 2:
        tr = table.rows[0]._tr
        trPr = tr.get_or_add_trPr()
        if trPr.find(qn("w:tblHeader")) is None:
            trPr.append(OxmlElement("w:tblHeader"))
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(2)
    return table


def callout(doc, title, body, fill="EEF4FA", bar="1F4E79"):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_tbl_width(table)
    keep_table_together(table)
    cell = table.cell(0, 0)
    shade_cell(cell, fill)
    set_cell_borders(cell, color=bar, sz="12")
    set_cell_margins(cell, top=80, bottom=80, left=140, right=140)
    cell.text = ""
    t = cell.paragraphs[0]
    t.paragraph_format.space_after = Pt(4)
    r = t.add_run(title)
    set_run_font(r, size=11, bold=True, color=NAVY)
    if isinstance(body, str):
        body = [body]
    for line in body:
        bp = cell.add_paragraph()
        bp.paragraph_format.space_after = Pt(2)
        bp.paragraph_format.space_before = Pt(0)
        bp.paragraph_format.line_spacing = 1.15
        rr = bp.add_run(line)
        set_run_font(rr, size=10.5, color=INK)
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(6)


def code_block(doc, text):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_tbl_width(table)
    cell = table.cell(0, 0)
    shade_cell(cell, "F6F8FA")
    set_cell_borders(cell, color="D0D7DE", sz="4")
    set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
    cell.text = ""
    first = True
    for line in text.split("\n"):
        para = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.line_spacing = 1.08
        run = para.add_run(line if line else " ")
        run.font.name = MONO
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), MONO)
        rFonts.set(qn("w:hAnsi"), MONO)
        rFonts.set(qn("w:eastAsia"), EAST)
        rFonts.set(qn("w:cs"), MONO)
        run.font.size = Pt(8)
        run.font.color.rgb = INK
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(8)


def build():
    doc = Document()
    configure_styles(doc)
    set_page(doc)
    add_header_footer(doc)

    # ===== COVER =====
    p(doc, "PAPERTRACE", size=11, bold=True, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2, space_before=4)
    p(doc, "工程落地计划书", size=26, bold=True, color=NAVY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    p(doc, "从技术规格到可提交的代码：修订、里程碑、验收与风险闸门", size=12, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)

    meta = [
        ("文档性质", "工程落地计划（吸收规格并修订）"),
        ("对应规格", "PaperTrace 技术规格书 v1.0（2026-11）"),
        ("计划版本", "v1.1  ·  2026-11-14"),
        ("工作区", r"D:\AgentPrograms\PaperTrace"),
        ("本机约束", "Windows  ·  RTX 5070 Ti Laptop 12GB  ·  系统 Python 3.13.15  ·  Ollama 未装"),
        ("黄金样例", "nanoGPT（强制关 flash） + Vaswani 2017（arXiv:1706.03762）"),
        ("默认模型", "Ollama qwen2.5-coder:7b  +  nomic-embed-text"),
        ("工期建议", "兼职 6–8 周；必须 3 周交差则停在 MVP-M3lite"),
    ]
    make_table(doc, ["项", "值"], meta, col_widths=[2.2, 7.8])

    callout(
        doc,
        "读这一页就能拍板",
        [
            "规格的方向是对的：「别人看结构，我们做对账」。v1 必须守住算子级、三步对齐、四类对账、trace.json 唯一契约、低置信不连线。",
            "规格里有 12 处如果照做，会在本机或产品定位上翻车。最危险的三句：默认 14B、fork deepwiki-open、用 GPT-2 论文做项级对齐。",
            "本计划把完整路径定为 M0→M5（约 50 个兼职日）。2–3 周只能交付 MVP-M3lite，不允许用假数据假装 M5 完成。",
        ],
    )

    p(doc, "配套文件（实现时以这些为准，本 Word 是给人读的决策稿）：", size=11, space_after=2, space_before=4)
    bullet(doc, r"可执行任务清单：docs\superpowers\plans\2026-11-14-papertrace-engineering-plan.md")
    bullet(doc, r"已冻结契约：schema\trace.schema.json（version 1.0 / schema_version 1.0.0）")
    bullet(doc, r"本机安装命令：docs\ENVIRONMENT.md")
    bullet(doc, r"规格抽取副本：_spec_extract.txt（原件在 Downloads）")

    # ===== 0 =====
    h1(doc, "0  这份计划在改什么、为什么改")
    p(doc, "规格书写得很完整：三个断层（认知、锚点、粒度）、四条原则、三步对齐、四类对账、L0–L3、stale 机制，这些全部保留。需要改的不是愿景，是「在这台电脑上、由一个大一兼职作者、在 2026 年冬天」怎么不翻车。")
    p(doc, "我把意见压成三条产品判断，后面的十二条修订都是这三条的推论。")

    h2(doc, "0.1  产品判断：对账有壁垒，看结构没有")
    p(doc, "规格第 2 章已经写对了：GitDiagram、DeepWiki、Google Code Wiki 把「看结构」做到免费且好用。再做一个仓库→Mermaid 的工具，周末就能被复刻，没有生存空间。PaperTrace 唯一值得做的切口是：论文公式项 ↔ 源码表达式 ↔ 实测 shape，三方对账，错了必须报，不确定必须进 unresolved。")
    p(doc, "所以本计划有一条总闸门：任何里程碑如果只能演示「一张好看的图」，而点不开「这一项公式对应哪一行、依据是什么」，就算没做完。M2 的播放器可以先没有左栏论文，但不许用假公式占位。")

    h2(doc, "0.2  工程判断：先代码侧闭环，再接论文")
    p(doc, "规格自己也说两边同时开工是这类项目最常见的失败方式。本计划把这一点写死：Task 3（fx 算子图）绿之前禁止开前端；Task 9（L0–L2 + sqlite）绿之前，论文 ingest 不得并进 build 默认路径。先能在关 flash 的 nanoGPT 上数清算子、看 shape 链不断，再谈对齐。")

    h2(doc, "0.3  资源判断：12GB 上 14B 不是默认，是可选")
    p(doc, "2026-11-14 本机实测：NVIDIA GeForce RTX 5070 Ti Laptop，总量 12227 MiB。规格默认 qwen2.5-coder:14b Q4 大约 9GB，再加一次 PyTorch forward 探针，会和系统显存抢到 OOM。判断题是 yes/no，7B 足够。14B 只允许在「只对齐、不跑探针」时手动切换。")

    add_picture(doc, "fig3_vram.png")
    caption(doc, "图 0-1  本机 12GB 显存分配。上条是规格默认，下条是本计划默认。")

    h2(doc, "0.4  十二条修订一览")
    p(doc, "实现时以本表为准，优于规格原文。未列入的规格硬规则一律遵守。", keep=True)
    make_table(
        doc,
        ["ID", "规格原文", "本计划", "一句话理由"],
        [
            ["S1", "默认 14B", "默认 7B", "12GB 上 14B+探针必 OOM"],
            ["S2", "fork deepwiki-open 作底座", "禁止 fork，自写 ingest", "它是文档生成器，不是算子图底座"],
            ["S3", "从 M1a 开工", "增加 M0 环境与夹具", "Ollama 未装，系统 Python 是 3.13"],
            ["S4", "默认 torch.export，失败再 fx", "M1a 主路径 fx", "nanoGPT 的 flash 分支是 Python if"],
            ["S5", "黄金论文用 GPT-2 报告", "改 Vaswani 2017", "Attention 公式不在 GPT-2 报告里"],
            ["S6", "marker / MinerU / Nougat", "优先 arXiv TeX", "PDF→LaTeX 是最大外部脆弱点"],
            ["S7", "L0–L2 全走模型", "L0 模板化，零 LLM", "规格自己写 L0「无（静态）」"],
            ["S8", "复用 code2flow / repo-visualizer", "不作为运行时依赖", "粒度是函数/文件，对不上算子"],
            ["S9", "Mermaid 作中间表示", "仅调试导出", "播放器吃 nodes/edges，不是 mermaid"],
            ["S10", "FastAPI 当后端框架", "只服务 localhost 深钻", "单文件 HTML 必须断网可开"],
            ["S11", "GPU hook + profiler", "探针默认 CPU", "与 LLM 互斥，tiny GPT 毫秒级"],
            ["S12", "2–3 周可用版本", "那是 MVP-M3lite，不是 M5", "完整路径兼职 6–8 周"],
        ],
        col_widths=[1.0, 2.6, 2.6, 3.8],
    )

    # ===== 1 =====
    h1(doc, "1  做成什么、明确不做的")
    h2(doc, "1.1  一句话定义（沿用规格，补上本机约束）")
    p(doc, "PaperTrace 是本地 CLI + 网页工具。输入一个 PyTorch 仓库（本地或 git）和一篇论文（arXiv TeX 优先，PDF 兜底），输出单文件 HTML：可播放的算子级数据流图，每个节点同时锚定源码行列与论文公式项，并给出是否等价的判定与依据。旁边永远有一份合法的 trace.json，它是唯一数据契约。")

    h2(doc, "1.2  三个断层，对应三条工程约束")
    make_table(
        doc,
        ["断层", "规格的意思", "本计划怎么钉死"],
        [
            ["认知", "仓库+论文，人脑四窗口拼接", "一个 HTML，三栏 jumpTo 同步；不允许再跳到四个网页"],
            ["锚点", "公式项、伪代码、源码行互不相通", "anchors 必填 evidence；低置信不连线，进 unresolved 清单"],
            ["粒度", "函数级对齐只能说到「大约第 3.2 节」", "fixture 强制 flash=False，图里必须出现独立的 matmul / scale / mask / softmax"],
        ],
        col_widths=[1.6, 3.5, 4.9],
    )

    h2(doc, "1.3  v1 明确不做（规格 1.4，全部保留）")
    bullet(doc, "不做多语言。只支持 Python + PyTorch。TF / JAX / C++ 全部拒绝并给出中文原因。")
    bullet(doc, "不做 Web 框架仓库。FastAPI / Django 的请求生命周期不是张量流。")
    bullet(doc, "不做账号、云、团队协作。产物是本地文件。")
    bullet(doc, "不做浏览器插件、IDE 插件。")
    bullet(doc, "不修改用户代码，不提交 PR。")
    bullet(doc, "不跑训练、不一键复现。只跑一次前向采集 trace。")
    p(doc, "本计划额外加两条「做了就算跑偏」：")
    bullet(doc, "不 fork、不 submodule、不 vendoring AsyncFuncAI/deepwiki-open。")
    bullet(doc, "不对用户展示 mock 数据。拿不到就空态 + 原因。")

    h2(doc, "1.4  目标用户（从规格收敛到「谁真会用第一版」）")
    p(doc, "规格表 1-1 列了研究生、开源作者、课程助教。第一版真正的用户是作者自己：把 nanoGPT 对着 Vaswani 公式项对账，能演示「点 QKᵀ 高亮到源码那一行」。对外能讲清楚差异化；对内能当课程作业/科研工具的种子。不要在 v1 为「任意仓库 + 任意 PDF」承诺准确率。")

    # ===== 2 =====
    h1(doc, "2  本机事实与环境闸门")
    p(doc, "这些数字是 2026-11-14 实测，不是规格里的假设。环境没打好之前不要写业务代码。", keep=True)
    make_table(
        doc,
        ["项", "实测值", "对计划的含义"],
        [
            ["GPU", "RTX 5070 Ti Laptop，12227 MiB，驱动 621.01", "12GB 档；7B Q4 留下约 6GB 余量"],
            ["系统 Python", "3.13.15，无 py launcher", "禁止用它跑 fx / 探针；必须另装 3.11 venv"],
            ["Ollama", "命令不存在，未安装", "M0 用 winget 安装，再 pull 7B 与 embed"],
            ["工作区", r"D:\AgentPrograms\PaperTrace 空仓起步", "本计划连仓库骨架一起定义"],
            ["捆绑 Python", "DSH runtime 有 python-docx / Pillow，无 matplotlib", "配图用 Pillow；项目代码不依赖捆绑解释器"],
        ],
        col_widths=[2.0, 4.0, 4.0],
    )

    h2(doc, "2.1  必须先做的安装（可复制）")
    p(doc, "管理员终端执行完，新开一个终端再确认版本。完整说明见 docs/ENVIRONMENT.md。", keep=True)
    code_block(
        doc,
        "winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements\n"
        "winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements\n"
        "\n"
        "cd /d D:\\AgentPrograms\\PaperTrace\n"
        "py -3.11 -m venv .venv\n"
        ".venv\\Scripts\\python.exe -m pip install -U pip\n"
        ".venv\\Scripts\\pip install torch --index-url \\\n"
        "    https://download.pytorch.org/whl/cu128\n"
        ".venv\\Scripts\\pip install pytest jsonschema sympy einops tree-sitter \\\n"
        "    tree-sitter-python lancedb fastapi uvicorn httpx numpy\n"
        "\n"
        "ollama pull qwen2.5-coder:7b\n"
        "ollama pull nomic-embed-text",
    )
    p(doc, "若 py -3.11 仍不可用，改用 Python311 安装目录下的 python.exe（通常在 AppData/Local/Programs/Python/Python311）。CUDA wheel 以能装上为准：cu128 失败再试 cu124。不要在 M0 装 marker / Nougat。")

    h2(doc, "2.2  环境变量（一次性冻结）")
    make_table(
        doc,
        ["变量", "默认", "含义"],
        [
            ["PAPERTRACE_LLM", "qwen2.5-coder:7b", "生成 / 判断题。禁止把 14b 写进默认"],
            ["PAPERTRACE_EMBED", "nomic-embed-text", "向量。禁止用生成模型打 embedding"],
            ["PAPERTRACE_DEVICE", "cpu", "探针设备。GPU 探针与 LLM 互斥"],
            ["PAPERTRACE_OLLAMA", "http://127.0.0.1:11434/v1", "OpenAI 兼容端点"],
        ],
        col_widths=[3.0, 3.2, 3.8],
    )

    # ===== 3 =====
    h1(doc, "3  十二条修订的完整理由")
    p(doc, "这一章是计划书的核心。规格写「可以改」，下面每条都给了本机证据或产品证据。不同意某条，就在该条上改，不要静默改回去。")

    amendments = [
        (
            "S1  默认模型从 14B 改为 7B",
            [
                "规格多处写死 qwen2.5-coder:14b。14B Q4 大约 9GB，本机总量 12GB。Ollama 常驻 + PyTorch 探针 + Windows 桌面，会挤爆。",
                "对齐主路径是判断题（只能 yes/no + 不超过 40 字依据），不是写长文。7B 编码模型足够。14B 仅在「只对齐、不跑 forward」时用环境变量切换。",
                "验收含义：A7「零外部 API 费」仍然成立；不把「必须 14B」写进 A1。",
            ],
        ),
        (
            "S2  禁止把 deepwiki-open 当底座",
            [
                "规格第 16 章：「deepwiki-open 是首选底座……这是一周与三个月的差别。」这是规格里最危险的一句。",
                "deepwiki-open（AsyncFuncAI，MIT）做的是仓库→wiki / Mermaid / 问答，缓存绑在 ~/.adalflow/wikicache/。它没有算子图、没有公式项、没有 shape、没有 source 三值。拿它当底座，产品会在第一周变成「又一个 DeepWiki + 一个论文附录」，对账切口被稀释。",
                "允许参考的只有三件事：仓库分块思路、结果缓存、Ollama 客户端。ingest/ 必须自写。",
            ],
        ),
        (
            "S3  增加 M0：环境与夹具",
            [
                "本机 Ollama 未装、系统 Python 3.13.15、无 py launcher。规格假设 Python 3.11 + 本地 14B 已经就绪。不先打环境，M1a 会在依赖上浪费一周。",
                "M0 的验收不是「装好了」，而是 pytest tests/test_env.py 绿：解释器是 3.11、schema 文件在、nanoGPT fixture 的 flash 为 False。",
            ],
        ),
        (
            "S4  M1a 主路径改为 torch.fx，export 作回归",
            [
                "规格写「默认走 torch.export，失败再 fx」。nanoGPT 的 CausalSelfAttention 用 Python if self.flash 选择 SDPA。export 对数据依赖控制流不友好，这正是规格自己承认 fx 更宽容的原因。",
                "先拿到可数的算子，再追求 export 的图稳定性。export 失败记入 meta.runtime，不阻断 M1a。",
                "更关键的是 flash：PyTorch≥2.0 默认 scaled_dot_product_attention，会把 QKᵀ、scale、mask、softmax 融成一个算子。fixture 必须写成 self.flash = False，否则项级对齐在图上没有对应节点。",
            ],
        ),
        (
            "S5  黄金论文从 GPT-2 报告改为 Vaswani 2017",
            [
                "规格 A1 / A3：nanoGPT + GPT-2 论文，播到 Attention 时左栏定位到 self-attention 段落。",
                "问题：GPT-2 是 Radford 2019 技术报告，Attention 公式的标准出处是 Vaswani et al. 2017（arXiv:1706.03762）。nanoGPT 注释写的是参考 GPT-2 实现（c_attn 一次投影再 split），不是参考 GPT-2 报告里的公式项。拿 GPT-2 PDF 做项级对齐，A3 会退化成「定位到一段散文」。",
                "本计划：主路径 Vaswani Attention 公式项；GPT-2 报告只作反向对账辅样例（实现超出论文描述：pre-LN、bias=False、weight tying、flash 融合）。数字仍用 GPT-2 124M：n_embd=768, n_head=12, head_dim=64。",
            ],
        ),
        (
            "S6  论文 ingest 优先 arXiv TeX",
            [
                "PDF→LaTeX（marker / MinerU / Nougat）是本项目最大的外部脆弱点。稳定 ID 如 §3.2-eq3 依赖真 LaTeX。arXiv 提供 .tar.gz 源码时，公式是作者写的 TeX，不是 OCR。",
                "优先级：本地 .tex → arXiv source tarball → marker PDF。MinerU 仅中文 PDF；Nougat 不做 v1（又大又慢，12GB 不值得）。marker 作为 extra：papertrace[pdf]。全部失败时 ingest_mode 记原因，unit_count=0，禁止伪造公式项。",
            ],
        ),
        (
            "S7  L0 模板化，零 LLM",
            [
                "规格表 11-1 写 L0「无（静态）」，正文却容易被读成 L0–L2 全量预生成都走模型。用 7B 给每个算子写「一句话职责」既烧 token 又不可复现。",
                "L0：由图元数据模板生成（op / loc / shape），测试 test_l0_does_not_call_llm 钉死 call_count==0。",
                "L1：规则 + 少量 LLM。L2：shape 序列由算子直接生成，LLM 只写一句人话，失败则只有模板。",
            ],
        ),
        (
            "S8  不把 code2flow / repo-visualizer 当依赖",
            [
                "code2flow 是函数调用图，repo-visualizer 是文件气泡图，粒度和算子对不上。引入它们等于多两套无关图，M2 还得扔掉。",
                "布局自写 Sugiyama，或可选 networkx。code2flow 只允许当调试脚本，对照「函数级 vs 算子级」给作者看，不进前端。",
            ],
        ),
        (
            "S9  Mermaid 只做调试导出",
            [
                "规格把 Mermaid 当中间表示。Mermaid 画不出逐 step 播放、shape 边标注、项级高亮、stale 虚线。",
                "唯一数据是 nodes/edges。scripts/dump_mermaid.py 把图打成 flowchart 便于人看，不进入前端构建。",
            ],
        ),
        (
            "S10  FastAPI 降级为 localhost 深钻服务",
            [
                "单文件 HTML 的验收是断网可开（A6 / A12）。把生成做成「必须起服务」会破坏这条。",
                "主路径：python -m papertrace build。serve 只为 L3 流式吐字。静态 HTML 里已有的 L0–L2 断网仍能看。",
            ],
        ),
        (
            "S11  探针默认 CPU，与 LLM 分时",
            [
                "见 S1。nanoGPT tiny 配置随机输入 forward 在 CPU 上是毫秒级，没必要默认上 GPU。",
                "GPU 探针与 Ollama 互斥：推理时卸载大 tensor。profiler 可选，不默认开。失败写 meta.runtime.reason，节点保持 source=static，不崩 CLI。",
            ],
        ),
        (
            "S12  2–3 周不是 M5，是 MVP-M3lite",
            [
                "规格第 18 章已经把路径拆成 M1a/b、M2、M2.5、M3、M4、M5，第 21 章又写「第一个可用版本 2–3 周：公式项→表达式 + 一张 Mermaid + 本地 HTML」。两句话放在一起会让执行者以为三周能齐活。",
                "完整 M0–M5：兼职每周 12–15 小时，约 6–8 周；全日大约 3.5–4.5 周。",
                "必须三周交差：停在 MVP-M3lite = M0+M1a+M1b+静态 SVG+公式项锚点+本地 HTML。不做播放动画、不做 L3、不做批量深钻。禁止用 mock 数据假装 M5 完成。",
            ],
        ),
    ]
    for title, paras in amendments:
        h3(doc, title)
        for t in paras:
            p(doc, t, space_after=6)

    callout(
        doc,
        "不改、必须守住的规格硬规则",
        [
            "trace.json 唯一契约；source ∈ {runtime, static, model}；低置信不连线；局部闭包重算。",
            "算子级而不是函数级；einops 展开；循环数据展开 / 视图折叠 ×N。",
            "三步对齐（检索 Top-5 → yes/no 判断题 → 结构加权）；四类对账（反向最重要）；L3 = 探针 + sympy 等价 + 对抗自检。",
            "闭包五项含「N 外变量赋值」；sqlite 存 raw_response；detail 只追加。",
            "stale：子结论与父矛盾 → conflicts + 父 stale:true，禁止静默覆盖。用户纠正进 annotations，重算作硬约束。",
            "三栏 jumpTo；播放器 {step, playing, speed} + rAF；默认模块级；KaTeX \\htmlId；语义色 ≤3；>300 算子确认；覆盖率常驻；单文件 <8MB。",
        ],
    )

    # ===== 4 =====
    h1(doc, "4  架构怎么落地")
    h2(doc, "4.1  两条输入、五个阶段")
    p(doc, "两条输入完全解耦，可以在不同时间完成。代码侧先跑通，论文侧后接。汇聚点只有 trace.json。", keep=True)
    add_picture(doc, "fig1_pipeline.png")
    caption(doc, "图 4-1  系统流水线。符号三元（D = n_embd = 768）是两侧的公共语言。")

    make_table(
        doc,
        ["阶段", "输入", "输出", "失败时"],
        [
            ["1 算子图", "nn.Module + 示例张量", "nodes/edges，source=static", "tree-sitter 降级，degraded=true"],
            ["2 公式项", "tex / arXiv / pdf", "paper units + terms", "ingest_mode=none，unit_count=0"],
            ["3 符号", "config + 公式符号", "mapping: matched / mismatch / only", "缺 defined_at 的符号不算数"],
            ["4 对齐", "code units × terms", "anchors + unresolved", "c<0.45 不连线"],
            ["5 对账/精读", "trace + 可选 L3", "mismatches / detail / stale", "缺探针字段拒绝写入"],
        ],
        col_widths=[1.8, 2.2, 3.2, 2.8],
    )

    h2(doc, "4.2  对齐引擎：判断题，不是生成题")
    p(doc, "规格第 8 章是本项目的灵魂。实现时有一条 grep 守卫：align 目录源码不得出现「生成对应关系」类接口。判断题的错误可解释（yes/no + 依据），生成题的错误不可解释。", keep=True)
    add_picture(doc, "fig2_align.png")
    caption(doc, "图 4-2  三步对齐。双向冲突时两边都降为黄或 unresolved，不得取平均抬过 0.75。")

    p(doc, "置信度写死，禁止让模型自己打分：")
    bullet(doc, "s_retr：双向 Top-5 的 max cosine，clip 到 [0,1]")
    bullet(doc, "s_judge：yes=1.0 / no=0.0；evidence 为空则强制 0")
    bullet(doc, "s_struct 初值 0.5：+0.2 层数同构；+0.1 超参名出现；+0.2 算子序列与公式项顺序同构（matmul→scale→softmax→matmul）；−0.4 shape 冲突；−0.3 双向 top1 不是同一对")
    p(doc, "权重写死：w_retr=0.30，w_judge=0.50，w_struct=0.20。c = sigmoid(w_retr·s_retr + w_judge·s_judge + w_struct·s_struct)。禁止让模型另给一个分数。")
    p(doc, "阈值：c≥0.75 绿实线；0.45≤c<0.75 黄虚线 + 1–2 备选；c<0.45 不连线，进 unresolved。")

    h2(doc, "4.3  模块边界")
    p(doc, "parse_code 不知道论文；parse_paper 不知道代码；align 只吃两侧产物；frontend 只吃通过校验的 trace.json。build_trace.py 是唯一编排入口。单源文件不超过 200 行。")

    # ===== 5 =====
    h1(doc, "5  数据契约 trace.json")
    p(doc, "schema 已冻结在 schema/trace.schema.json。version 恒为 1.0，schema_version 恒为 1.0.0。additionalProperties=false。改字段必须同步改校验器与本计划。")
    p(doc, "根对象必填十个键：meta, symbols, nodes, edges, anchors, mismatches, unresolved, annotations, conflicts, view_state。")

    h2(doc, "5.1  节点与边")
    make_table(
        doc,
        ["字段", "约束", "备注"],
        [
            ["nodes[].source", "runtime / static / model", "界面必须能区分，对应 A4"],
            ["nodes[].degraded", "bool；true 时 degraded_reason 非空", "fx 失败走 tree-sitter"],
            ["nodes[].repeat", "整数 ≥1", "折叠层写在代表节点上"],
            ["nodes[].stale", "bool", "子结论打脸父结论时为 true"],
            ["nodes[].detail", "只追加 L0–L3", "禁止覆盖旧层级"],
            ["edges[].shape_consistent", "bool", "推不出填 false，不得用 null 冒充"],
        ],
        col_widths=[2.8, 3.4, 3.8],
    )

    h2(doc, "5.2  锚点（对账的最小单位）")
    p(doc, "必填：paper_unit_id, formula_term_index, code_expr_range, aten_ops, confidence, source, evidence。evidence 最少 1 字符、最多 80 字符（界面按 40 字截断）。空 evidence 的锚点校验失败。alternatives 最多 2 条。verified_by 只能是 null 或 user。")

    h2(doc, "5.3  符号三元")
    p(doc, "代码侧冻结符号名：B, T, D, H, Dh（Dh = D/H）。nanoGPT / GPT-2 124M：D=n_embd=768，H=n_head=12，Dh=64，T=block_size。mapping.status ∈ {matched, value_mismatch, code_only, paper_only}。每个代码符号必须有 defined_at。")

    h2(doc, "5.4  L3 必填三项")
    p(doc, "detail.L3 缺 probe / equivalent / adversarial 任一字段则拒绝写入。adversarial 在 LLM 不可用时允许规则清单 + conclusion=unknown，这不算失败；缺字段才算失败。")

    h2(doc, "5.5  缓存键")
    p(doc, "cache_key = sha256(commit + 闭包源码 + 论文单元 + level + 模型 + prompt_version)。禁止用整仓哈希。改无关函数后，未受影响节点命中率必须 100%（A9）。闭包五项必须包含「N 外变量赋值」，例如 n_embd 定义在 GPTConfig / __init__。")

    # ===== 6 =====
    h1(doc, "6  目录、技术栈、CLI")
    h2(doc, "6.1  仓库目录")
    code_block(
        doc,
        "papertrace/\n"
        "  pyproject.toml\n"
        "  schema/trace.schema.json          # 已存在\n"
        "  papertrace/\n"
        "    cli.py                          # build | dump | serve | eval\n"
        "    schema_validate.py\n"
        "    ingest/{repo,paper,arxiv}.py\n"
        "    parse_code/{fx_trace,einops_expand,loop_fold,\n"
        "                treesitter_fallback,loc}.py\n"
        "    parse_paper/{units,split_terms,latex_safe}.py\n"
        "    symbols/{code_table,paper_table,mapping,shape_prop}.py\n"
        "    align/{embed,retrieve,judge,score}.py\n"
        "    diff/{dim,struct,missing,reverse}.py\n"
        "    trace_runtime/{discover,probe,profile}.py\n"
        "    detail/{l0,l1,l2,l3,closure,cache,stale,annotations}.py\n"
        "    llm/{client,prompts}.py         # JUDGE_PROMPT 与 DRILL_PROMPT 禁止混用\n"
        "    build_trace.py                  # 唯一编排\n"
        "  frontend/src/{views,player,render,panel,jumpTo.ts}\n"
        "  tests/fixtures/nanogpt/           # 关 flash 的 vendor 副本\n"
        "  tests/fixtures/papers/vaswani2017/\n"
        "  data/{cache.db,golden/}\n"
        "  output/{index.html,trace.json}",
    )

    h2(doc, "6.2  技术栈（相对规格的取舍）")
    make_table(
        doc,
        ["层", "选用", "不用 / 降级"],
        [
            ["语言", "Python 3.11 venv", "系统 3.13"],
            ["图", "torch.fx 主路径", "export 仅回归"],
            ["符号", "sympy；latex2sympy2 容错", "失败保留 raw LaTeX"],
            ["论文", "arXiv TeX；marker 可选", "Nougat 不做 v1"],
            ["检索", "LanceDB + nomic-embed-text", "生成模型打向量"],
            ["LLM", "Ollama 7B，localhost", "任何付费 API"],
            ["缓存", "sqlite3", "云 KV"],
            ["前端", "Vite + TS + SVG + KaTeX + singlefile", "React 大框架非必须"],
            ["服务", "FastAPI 只 serve 深钻", "生成依赖常驻服务"],
        ],
        col_widths=[1.8, 4.2, 4.0],
    )

    h2(doc, "6.3  CLI 契约")
    code_block(
        doc,
        "python -m papertrace build  --repo <path|url> --paper <arxiv:ID|path> --out output/\n"
        "python -m papertrace dump   --trace output/trace.json --mermaid output/debug.mmd\n"
        "python -m papertrace serve  --trace output/trace.json --host 127.0.0.1 --port 8765\n"
        "python -m papertrace eval   --golden data/golden",
    )
    p(doc, "build 成功：写出通过 validate_trace 的 json；前端可缺论文（unresolved 会很多）但不得缺 nodes。失败：非零退出，stderr 中文。非 PyTorch 仓库不得写残缺 HTML。算子 >300 必须 --yes 或交互确认。")

    # ===== 7 =====
    h1(doc, "7  里程碑与兼职日历")
    p(doc, "按每周有效开发 12–15 小时估（大一 + 助教，时间碎）。全日大约乘 0.55。日期从 M0 开工起算，不是从今天起算。", keep=True)
    make_table(
        doc,
        ["里程碑", "日历", "必须能看到的东西", "对应 Task"],
        [
            ["M0 环境与夹具", "D1–D2", "venv 3.11、Ollama 7B、test_env 绿", "0"],
            ["M1a 算子追踪", "D3–D8", "tiny nanoGPT 算子可数，shape 链不断", "1–5"],
            ["M1b 符号", "D9–D12", "n_embd=768 ↔ D，每个维度有 defined_at", "6–7"],
            ["M2 图+播放器", "D13–D19", "中栏+右栏，200 step 连播不卡；左栏空态", "8"],
            ["M2.5 L0–L2+sqlite", "D20–D23", "改 GELU 一行，Attention 缓存 100% 命中", "9"],
            ["M3 论文对齐", "D24–D33", "点 matmul_qk，左栏亮到 QKᵀ 项", "10–11"],
            ["M4 L3+四对账", "D34–D40", "GQA 陷阱报 struct + 父 stale", "12–13"],
            ["M5 单文件+纠正", "D41–D46", "断网打开 <8MB HTML，纠正后重算遵守", "14"],
            ["缓冲 / golden", "D47–D50", "Attention 8 对人工标注 + 对照组", "15"],
        ],
        col_widths=[2.4, 1.6, 4.2, 1.8],
    )
    add_picture(doc, "fig4_milestones.png", width_cm=15.2)
    caption(doc, "图 7-1  里程碑依赖。M2.5 必须插在接论文之前，分层与缓存定错是最贵的返工。")

    h2(doc, "7.1  MVP-M3lite（只有必须三周交差时才启用）")
    p(doc, "范围：M0 + M1a + M1b + 静态 SVG + 公式项锚点 + 本地 HTML。砍掉：播放器动画、L3、批量深钻、singlefile 体积极限打磨。A2 流动画、A8 0.6× 允许写进「未完成」。仍然禁止 mock 数据。")
    p(doc, "建议：除非有硬截止日期，不要启用这条。对账工具的演示瞬间是「点一项公式，三栏同时亮」，这已经需要 M3，不需要 M5。")

    # ===== 8 =====
    h1(doc, "8  任务拆解（给人看的版本）")
    p(doc, "下面每项写清：产出、验收数字、禁止事项。逐步测试代码与提交说明在配套 markdown 计划里，给执行者（人或 agent）按 Task 0→15 勾。这里不把代码抄进 Word。")
    p(doc, "总顺序铁律：Task 3 绿之前禁止开 Task 8。Task 9 绿之前，Task 10 不得并进 build 默认路径。先不要装 marker。")

    tasks = [
        (
            "Task 0  ·  M0 环境、骨架、夹具",
            "pyproject.toml、CLI --help、tests/fixtures/nanogpt（只 vendor model.py）、docs/ENVIRONMENT.md。",
            [
                "sys.version_info == (3, 11)",
                "CausalSelfAttention.flash is False，注释写明原因",
                "python -m papertrace --help 退出码 0，版本 0.1.0",
            ],
            "不要 vendor 训练脚本；不要在这一步装 marker。",
        ),
        (
            "Task 1  ·  Schema 校验器",
            "validate_trace / minimal_trace / load_trace / dump_trace。非法抛 TraceSchemaError。",
            [
                "缺 source 的 node 被拒",
                "anchors.evidence 为空被拒",
                "空骨架（无节点）可以通过",
            ],
            "改 schema 必须写进提交说明。",
        ),
        (
            "Task 2  ·  仓库 ingest",
            "ingest_repo → RepoMeta(url, commit, language='python', entry_module)。find_pytorch_modules 找 nn.Module 子类。",
            [
                "本地 fixture 返回 ≥7 位 commit；无 git 时 dirty-<sha256[:12]>",
                "空目录、纯 Django 假仓库抛 IngestError，中文原因",
            ],
            "非 Python / 找不到 torch 导入不得继续。",
        ),
        (
            "Task 3  ·  M1a 主路径 torch.fx",
            "trace_module(mod, args) → FxBundle。tiny 配置：n_layer=1, n_embd=32, n_head=4, block_size=8, vocab=64。",
            [
                "Attention 非 flash 路径至少：matmul(QK) + mul(scale) + masked_fill + softmax + matmul(AV)",
                "全图 shape_consistent 为 True",
                "每个 node.loc 匹配 model.py:行号",
            ],
            "symbolic_trace 因 if 失败时，对 CausalSelfAttention / MLP / Block 分别 trace 再堆叠。禁止因此改回 flash=True。dump_mermaid 只用于人看。",
        ),
        (
            "Task 4  ·  einops 展开与循环折叠",
            "expand_einops、fold_repeats。解析走 einops 自己的 parse。",
            [
                "'b t (h d) -> b h t d' 展开后节点数 ≥3，最终符号 shape [B,H,T,D]",
                "n_layer=12 时代表节点 repeat==12，view_state.collapsed 默认含 block 前缀",
            ],
            "禁止手写正则当主路径。",
        ),
        (
            "Task 5  ·  tree-sitter 降级",
            "fx 失败捕获异常，fallback_ast，节点 degraded=True 且 reason 非空。CLI 不得崩溃。",
            ["含 if tensor.sum() > 0 的假 Module 结果 degraded is True"],
            "降级图仍要能被 schema 接受。",
        ),
        (
            "Task 6  ·  M1b 符号与 shape 传播",
            "build_code_symbols、propagate_shapes。符号名冻结 B,T,D,H,Dh。",
            [
                "124M 数字、n_layer=1：n_embd → D=768，Dh=64，所有符号有 defined_at",
                "推不出的边 shape_consistent=False，不得填 None 冒充",
            ],
            "不要在这一步接论文符号，先把代码侧三元跑通。",
        ),
        (
            "Task 7  ·  CPU 运行时探针",
            "run_forward(..., device='cpu')。匹配到的 node source 改为 runtime。失败写 meta.runtime。",
            [
                "tiny GPT CPU forward 后 Attention 输出 shape [1,8,32]",
                "缺权重 / 错误 vocab 不抛到 CLI",
            ],
            "不要默认开 profiler；不要默认 GPU。",
        ),
        (
            "Task 8  ·  M2 图、播放器、右栏代码",
            "jumpTo 唯一滚动入口。PlayerState={step,playing,speed}，rAF 推进。三级缩放默认 module。本任务不实现左栏论文。",
            [
                "speed=1 连播 200 step，step 从 0 到 199，无回跳",
                "当前 step 描边加粗；右栏按 loc 切片源码",
                "source 角标；degraded 虚线框；语义色最多 3 个",
            ],
            "禁止 setTimeout 推进 step；禁止假公式占位；播放器不要渐变发光粒子。",
        ),
        (
            "Task 9  ·  M2.5 L0–L2 与 sqlite",
            "render_l0 不得调用 LLM。Cache 表 (key PK, level, node_id, raw_response, created_at)。closure 五项并集。",
            [
                "test_l0_does_not_call_llm：fake client call_count==0",
                "改 MLP.GELU 为 SiLU 后重算，Attention 节点 key 不变、命中率 100%",
                "L2 文本先是 shape 序列模板，LLM 失败则只有模板",
            ],
            "闭包缺「N 外变量赋值」视为 bug。JUDGE 与 DRILL 提示词此步先分开文件位置。",
        ),
        (
            "Task 10  ·  论文 ingest（TeX 优先）",
            "ingest_paper(arxiv: / .tex / .pdf)。split_formula 停在可辨识算子。latex_to_sympy_safe 失败保留 raw。",
            [
                "Vaswani 注意力公式至少拆 4 项：QKᵀ、/√d_k、softmax、×V",
                "稳定 ID 例：§3.2-eq-attn-t0..t3",
                "坏 latex \\unknownmacro{x} 不抛，ok=False",
            ],
            "v1 不装 Nougat。fixture 只抽 Attention 一节最小 tex，不要一上来 ingest 整本 15 页。",
        ),
        (
            "Task 11  ·  M3 三步对齐",
            "embed_texts、retrieve_bidirectional(k=5)、judge → JudgeResult(yes, evidence)、confidence 用冻结权重。",
            [
                "prompt 含「只能回答 yes / no」，不含「请列出对应关系」",
                "softmax 项对 F.softmax → c≥0.75；对 nn.Linear → c<0.45 进 unresolved",
                "grep 守卫：align 源码禁止 generate_alignment / 「对应关系如下」",
                "左栏 KaTeX + htmlId，jumpTo({paperUnitId}) 三栏同步",
            ],
            "函数签名不得出现由模型一次生成的 mapping: dict。双向冲突不得取平均抬过 0.75。",
        ),
        (
            "Task 12  ·  四类对账",
            "run_diff → type ∈ {dim, struct, missing, reverse}。反向对账 v1 写死检测器，不靠 LLM。",
            [
                "GQA 陷阱：n_kv_head=2, n_head=8，注释仍写 Multi-Head → struct，severity high 或 medium",
                "nanoGPT 至少 1 条 reverse（pre-LN / bias / weight tying，以代码为准）",
                "人为 head_dim=96 对论文 Dh=64 → dim",
            ],
            "反向检测器清单：weight tying、bias=False、pre-LN vs post-LN、causal mask（tril vs -inf）、flash fusion 是否发生。",
        ),
        (
            "Task 13  ·  L3 三项验证 + stale",
            "drill_l3 缺三项任一则抛。equivalent：simplify(a-b)==0。probe：CPU 随机输入。adversarial：二次询问或规则清单。",
            [
                "缺 probe 的假写入被拒",
                "GQA 上父 L0 若仍写「标准 MHA」则 stale",
                "POST /drill SSE 流式；静态 HTML 断网仍能看 L0–L2",
            ],
            "DRILL_PROMPT 必须含「已知父节点结论为 X，请核对 Y，不成立给反例」。与 JUDGE_PROMPT 不得共用。",
        ),
        (
            "Task 14  ·  M5 导出、纠正、未定位清单",
            "singlefile HTML；apply_annotation；覆盖率文案；预算条；>300 算子确认。",
            [
                "纠正「scale 在 softmax 后」为「之前」后，L3 含该纠正",
                "至少一个 unresolved 出现在 UI 清单，不是绿线",
                "HTML < 8_000_000 字节；断网文件协议可开",
            ],
            "KaTeX 只内联用到的字体子集；图片不内联。serve 不是 A6 验收路径。",
        ),
        (
            "Task 15  ·  Golden set 与对照组",
            "8 条 Attention 项人工标注 + scripts/eval_align.py。对照组：同一 8 条直接问通用模型「公式 X 对应哪一行」。",
            [
                "8 条：QK、scale、mask、softmax、AV、c_attn split、c_proj、残差 add",
                "评估脚本无 UI 可跑",
                "工具赢不了对照组 → 不得宣称 A3 通过，只能写 unresolved 率",
            ],
            "golden 是存在理由。没有对照组的「我们对得上」是自说自话。",
        ),
    ]
    for title, output, checks, forbid in tasks:
        h3(doc, title)
        rich(doc, [("产出。", {"size": 11, "bold": True, "color": INK}), (output, {"size": 11, "color": INK})], space_after=4)
        p(doc, "验收。", size=11, bold=True, space_after=2)
        for c in checks:
            bullet(doc, c)
        rich(doc, [("禁止。", {"size": 11, "bold": True, "color": RED}), (forbid, {"size": 11, "color": INK})], space_after=8, space_before=4)

    # ===== 9 =====
    h1(doc, "9  黄金样例：nanoGPT 必须对上的结构")
    p(doc, "实现 Attention 追踪时，下列结构必须在脑子里，也必须出现在测试里。这是 2026-11-14 对着 nanoGPT model.py 核对过的。")

    h2(doc, "9.1  CausalSelfAttention")
    bullet(doc, "c_attn: Linear(n_embd, 3*n_embd)，一次投影后 .split(n_embd, dim=2) 得 q,k,v。")
    bullet(doc, "reshape / transpose 到 (B, n_head, T, hs)，hs = C // n_head。")
    bullet(doc, "原代码：self.flash = hasattr(F, 'scaled_dot_product_attention')。PyTorch 2+ 默认为 True。")
    bullet(doc, "fixture 改为 self.flash = False。非 flash 路径：att = (q @ k.T) * (1/sqrt(hs)) → masked_fill(tril==0, -inf) → softmax → att @ v。")
    bullet(doc, "c_proj: Linear(n_embd, n_embd) 把多头拼回去。")

    h2(doc, "9.2  MLP 与 Block")
    bullet(doc, "MLP：Linear(D, 4D) → GELU → Linear(4D, D)。")
    bullet(doc, "Block：pre-LN。x + attn(ln1(x))，x + mlp(ln2(x))。这是一条 reverse 对账：Vaswani 原文是 post-LN。")

    h2(doc, "9.3  数字")
    p(doc, "GPT-2 124M / nanoGPT 默认：n_embd=768, n_head=12, n_layer=12, block_size=1024, vocab=50304。head_dim = 768/12 = 64，与 Vaswani 的 d_k 叙述同构。测试图用 tiny 配置，避免 124M 权重；符号表测试才用 768/12/64 这些数字。")

    h2(doc, "9.4  为什么不能用 GPT-2 报告当主论文")
    p(doc, "nanoGPT 实现的是 GPT-2 结构（合并 QKV 投影、pre-LN、可学习位置编码等），公式语言却来自 Attention is All You Need。项级对齐要对「表达式」，不是对「这篇实现参考了哪篇工作」。GPT-2 报告保留为反向对账辅样例：代码里有、论文里没写的，必须报 reverse，这正是规格说「最重要」的那一类。")

    # ===== 10 =====
    h1(doc, "10  验收映射（规格 A1–A12）")
    p(doc, "规格要求验收是可当场点的句子。下表把每条接到本计划的 Task，并标出相对规格的差异。", keep=True)
    make_table(
        doc,
        ["ID", "规格通过条件", "本计划", "差异"],
        [
            ["A1", "nanoGPT + GPT-2 论文，5 分钟出 HTML", "nanoGPT + Vaswani；计时从 CLI 起，不含首次 ollama pull", "S5 改论文"],
            ["A2", "播放、流动画、shape 与实测一致", "Task 8+7；MVP 可无动画仍显示当前节点", "动画可后置"],
            ["A3", "Attention 时三栏定位到段落/行", "定位到 Vaswani 公式项 + CausalSelfAttention 行", "项级，不是段落"],
            ["A4", "能区分 runtime/static/model", "schema + 角标", "无"],
            ["A5", "未定位项进清单，不强行连线", "c<0.45 进 unresolved；UI 必须列出", "无"],
            ["A6", "断网打开 index.html", "singlefile；serve 不是验收路径", "S10"],
            ["A7", "零外部 API 费", "只走 Ollama", "模型改为 7B"],
            ["A8", "批量深钻 <0.6×", "Task 13，可后置", "MVP 可延期"],
            ["A9", "改一函数，未受影响命中 100%", "闭包级 cache_key，Task 9", "无"],
            ["A10", "MHA→GQA 报 mismatch 且父 stale", "Task 12+13 写死陷阱", "无"],
            ["A11", "用户纠正后重算遵守", "annotations 注入 prompt 前置", "无"],
            ["A12", "断网可浏览已生成层级", "L0–L2 预写入 HTML", "L3 需 serve"],
        ],
        col_widths=[1.1, 3.2, 3.5, 2.2],
    )
    p(doc, "A3 的额外闸门：工具在 8 条 golden 上赢不了「直接问通用模型」的对照组，不得宣称 A3 通过。")

    # ===== 11 =====
    h1(doc, "11  风险登记与闸门")
    p(doc, "规格表 20-1 的风险都还在。本计划给每条加了一道能在代码里检查的闸门，而不是「注意一下」。")
    make_table(
        doc,
        ["风险", "闸门", "落在哪"],
        [
            ["Token 爆炸", "L0 零 LLM；Top-5 不塞全文；预算条；>300 确认", "T9 / T14"],
            ["幻觉连线", "判断题；evidence 必填；grep 守卫禁止生成对齐", "T11"],
            ["项级天花板", "unresolved 是功能；golden 8 条先测天花板", "T15"],
            ["局部对、整体错", "覆盖率常驻：「仍有 N 个节点停在 L0/L1」", "T14"],
            ["prompt 混用", "JUDGE_PROMPT vs DRILL_PROMPT 两个常量；drill 必须带父结论", "T11 / T13"],
            ["fx / latex2sympy2 脆", "三级降级；raw LaTeX 始终保留", "T5 / T10"],
            ["HTML 体积", "测试卡 8MB；字体子集；图不内联", "T14"],
            ["无评估", "对照组是存在理由；赢不了不宣称 A3", "T15"],
            ["14B OOM", "默认 7B；探针 CPU", "S1 / S11"],
            ["deepwiki 底座跑偏", "禁止 fork", "S2"],
            ["黄金论文选错", "Vaswani 主路径", "S5"],
            ["时间碎 / 假完整", "MVP-M3lite 可交差；禁止 mock 齐活", "S12"],
            ["缓存键过粗", "闭包源码入 key，禁止整仓哈希", "T9"],
            ["空仓 / 非 PyTorch", "非零退出 + 中文原因，不写残缺 HTML", "T2"],
        ],
        col_widths=[2.2, 5.0, 2.8],
    )

    h2(doc, "11.1  Review Focus（最可能咬人的八条）")
    p(doc, "这些是规格暗示、但一不小心就会在实现里漏测的输入。配套 markdown 计划把测试钉在对应 Task 上。")
    bullet(doc, "flash 融合：fixture 若忘了关，图上只剩一个 SDPA，项级对齐破产。")
    bullet(doc, "export 失败：不得阻断 M1a。")
    bullet(doc, "论文 ingest 失败：禁止伪造公式项。")
    bullet(doc, "12GB 争用：7B 与 model.forward 不得同时占满 GPU。")
    bullet(doc, "缓存键过粗：改 GELU 不得使 Attention 缓存失效。")
    bullet(doc, "自由生成对齐：任何 align 代码路径直接输出「公式→行号」视为失败。")
    bullet(doc, "L0 烧模型：test_l0_does_not_call_llm。")
    bullet(doc, "空仓库 / 非 PyTorch：CLI 非零退出。")

    # ===== 12 =====
    h1(doc, "12  前端与演示纪律")
    p(doc, "规格第 15 章的前端规格全部保留，这里只强调会让产品看起来像「又一个架构图网站」的点。")
    bullet(doc, "三栏：论文 / 图 / 代码。跳转只走 jumpTo({paperUnitId | symbolId | stepIndex})。")
    bullet(doc, "播放器状态机 {step, playing, speed}，rAF 推进，禁止 setTimeout 走步。")
    bullet(doc, "默认缩放模块级。stage / module / op 三级。循环层默认折叠，repeat=N 写在代表节点。")
    bullet(doc, "KaTeX 用 htmlId 做项级高亮，不要整段闪。")
    bullet(doc, "语义色 ≤3：绿置信、黄待核、橙红 mismatch。source 用角标，不用第四种颜色。")
    bullet(doc, "覆盖率常驻，预算条常驻。算子 >300 先确认。")
    bullet(doc, "未接入论文时左栏写「未接入论文」，不要放假公式。")
    bullet(doc, "视觉：播放器控件不要渐变发光粒子。这是对账工具，不是落地页。")

    # ===== 13 =====
    h1(doc, "13  需要你拍板的四件事")
    p(doc, "计划可以按默认走。但下面四件会改变日历或黄金样例，最好你看完这一节再开工。")

    h3(doc, "Q1  工期按哪条？")
    bullet(doc, "推荐：兼职 6–8 周走完 M0–M5。")
    bullet(doc, "若有硬截止日期（比赛、课设）：启用 MVP-M3lite，A2/A8 延期。")
    bullet(doc, "不推荐：口头「三周做完 M5」。那会逼出假数据。")

    h3(doc, "Q2  黄金论文改 Vaswani，同不同意？")
    p(doc, "这是对规格 A1/A3 的实质性修改。不同意的话，主路径仍用 GPT-2 报告，但项级对齐大概率只能对到段落，A3 的「公式项」会缩水。我建议同意。GPT-2 报告仍留作反向对账。")

    h3(doc, "Q3  现在是否安装 Python 3.11 + Ollama + 7B？")
    p(doc, "M0 的命令已经写在第 2 章。磁盘大约还要 5–8GB（7B Q4 + embed）。14B 先不要拉。")

    h3(doc, "Q4  计划审过之后，代码怎么写？")
    bullet(doc, "配套 markdown 已按 writing-plans 拆成 Task 0–15，可按任务交给子 agent，或我在本会话按任务实现。")
    bullet(doc, "推荐：你先确认第 3 章十二条和第 13 章四问；确认后再动代码。Task 3 绿之前不要碰前端。")

    callout(
        doc,
        "我作为执行者的默认假设（你不反对就按这个做）",
        [
            "工期走兼职 6–8 周，不启用 MVP-M3lite。",
            "黄金主路径：关 flash 的 nanoGPT + Vaswani 2017 Attention 公式。",
            "默认模型 7B，探针 CPU。",
            "不 fork deepwiki-open。",
            "先 M0 环境，再 schema，再 fx。论文侧在 M2.5 之后才进默认 build。",
        ],
        fill="EAF6EF",
        bar="027A48",
    )

    # ===== 14 =====
    h1(doc, "14  给执行者的第一周")
    p(doc, "不要写前端，不要装 marker，不要拉 14B，不要 ingest 整篇 PDF。", keep=True)
    make_table(
        doc,
        ["日", "做什么", "结束时能证明什么"],
        [
            ["D1", "装 Python 3.11、Ollama、venv、torch cu128", "import torch 打出 5070 Ti 与 12227 MiB"],
            ["D1", "pull 7B 与 nomic-embed-text", "curl 11434/api/tags 看得到两个模型"],
            ["D2", "仓库骨架 + nanoGPT fixture 关 flash", "pytest tests/test_env.py 全绿"],
            ["D2", "schema 校验器", "缺 source / 空 evidence 被拒"],
            ["D3–D4", "fx 追踪 tiny GPT", "Attention 五件套算子可数"],
            ["D5", "loc 回填 + dump_mermaid 人工看图", "每个节点有 model.py:行号"],
            ["D6–D8", "einops / 折叠 / tree-sitter 降级", "M1a 可演示：一张真算子图"],
        ],
        col_widths=[1.6, 4.4, 4.0],
    )
    p(doc, "第一周结束的演示标准：打开 dump 出来的 mermaid 或 SVG，能指着 softmax 节点说「这是 model.py 第 N 行，shape 是 [B,H,T,T]」。还没有论文，这是故意的。")

    # ===== 15 =====
    h1(doc, "15  规格覆盖自检")
    p(doc, "对照规格目录，确认没有把整章漏掉。")
    make_table(
        doc,
        ["规格章节", "本计划落点", "备注"],
        [
            ["0–1 定位 / 不做", "第 1 章", "范围原样保留，加两条跑偏闸门"],
            ["2 现有工具", "0.1 / S2", "差异化仍是对账"],
            ["3 架构", "第 4 章 + 图 4-1", "先代码后论文"],
            ["4 trace.json", "第 5 章 + schema 文件", "已冻结"],
            ["5 算子级解析", "Task 3–5，S4", "关 flash"],
            ["6 符号系统", "Task 6，第 5.3 节", "三元映射四态"],
            ["7 论文侧", "Task 10，S6", "TeX 优先"],
            ["8 对齐引擎", "Task 11，图 4-2", "grep 守卫"],
            ["9 差异检测", "Task 12", "反向写死检测器"],
            ["10 运行时", "Task 7，S11", "默认 CPU"],
            ["11–13 L0–L3 / 闭包", "Task 9 / 13，S7", "L0 零 LLM"],
            ["14 stale / 纠正", "Task 13–14", "禁止静默覆盖"],
            ["15 前端", "Task 8 / 14，第 12 章", "左栏可空不可假"],
            ["16 技术栈", "第 6 章，S2/S8/S9", "不 fork、不靠调用图工具"],
            ["17 目录", "第 6.1 节", "FastAPI 降为 serve"],
            ["18 里程碑", "第 7 章，S3/S12", "加 M0"],
            ["19 验收", "第 10 章", "A1/A3 论文改为 Vaswani"],
            ["20 风险", "第 11 章", "每条有闸门"],
            ["21 实施建议", "第 14 章", "2–3 周定义为 MVP"],
            ["附录 A/B 提示词", "prompts.py 实现时迁移", "本 Word 不展开复制；初次与深钻不得共用"],
            ["附录 C 一致性", "已吸收；本计划再修 12 处", "规格已修 10 处，本计划是第二轮"],
        ],
        col_widths=[2.6, 3.4, 4.0],
    )

    h2(doc, "15.1  已知接受的缺口（规格附录 C + 本计划）")
    bullet(doc, "项级准确率有天花板。unresolved 是产品功能，不是失败。")
    bullet(doc, "中文公式不稳。v1 主路径英文 TeX。")
    bullet(doc, "非 PyTorch 无 runtime。静态降级或直接拒绝。")
    bullet(doc, "7B 判断题仍会错。所以必须 evidence + 源码可点开 + 对照组。")
    bullet(doc, "本机尚未安装 Ollama / Python 3.11。计划默认假设你同意第 13 章 Q3。")

    # ===== 16 =====
    h1(doc, "16  结语")
    p(doc, "规格已经把「做成什么」讲清楚了。这份计划书做三件规格没做完的事：把愿景钉在这台 12GB 笔记本上；把会让产品跑偏的底座和论文选择改掉；把 2–3 周能交的和 6–8 周能成的切开。")
    callout(
        doc,
        "如果只记四句",
        [
            "别人看结构，我们做对账。假数据等于没做。",
            "默认 7B，探针走 CPU，不 fork DeepWiki。",
            "关 flash 的 nanoGPT 算子图是第一张能演示的东西；Vaswani 公式项是第一张能对账的东西。",
            "判断题可解释，生成题不可解释。低置信就进清单，不要连绿线。",
        ],
    )
    p(doc, "下一步：你看第 3 章和第 13 章。点头之后从 Task 0 开始。完整勾选步骤在配套 markdown 计划里。", space_before=4)
    p(doc, "— 完 —", size=11, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=10)

    doc.save(str(OUT))
    print("saved", OUT, "bytes", OUT.stat().st_size)


if __name__ == "__main__":
    build()
