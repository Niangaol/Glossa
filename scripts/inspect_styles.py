# -*- coding: utf-8 -*-
from docx import Document
from docx.oxml.ns import qn
from pathlib import Path

p = Path(r"D:\AgentPrograms\PaperTrace\PaperTrace_工程落地计划书.docx")
doc = Document(str(p))

def dump_ppr(name, pPr, limit=40):
    if pPr is None:
        print(name, "NO pPr")
        return
    kids = [c.tag.split("}")[-1] for c in pPr]
    print(name, "pPr:", kids)
    for tag in ("pageBreakBefore", "keepNext", "keepLines", "widowControl"):
        el = pPr.find(qn(f"w:{tag}"))
        if el is not None:
            print(" ", tag, el.attrib)

for name in ("Normal", "Heading 1", "Heading 2", "Title"):
    st = doc.styles[name]
    dump_ppr(f"STYLE {name}", st.element.find(qn("w:pPr")))

# first few headings in body
n = 0
for para in doc.paragraphs:
    style = para.style.name if para.style else ""
    if style == "Heading 1":
        dump_ppr(f"BODY H1 {para.text[:40]!r}", para._p.find(qn("w:pPr")))
        n += 1
        if n >= 3:
            break

# table widths
print("TABLE WIDTHS")
for i, t in enumerate(doc.tables[:6]):
    tbl = t._tbl
    tblW = tbl.tblPr.find(qn("w:tblW")) if tbl.tblPr is not None else None
    print(i, "tblW", None if tblW is None else (tblW.get(qn("w:w")), tblW.get(qn("w:type"))), "rows", len(t.rows), "cols", len(t.columns))

# docDefaults
body = doc.element.body
sect = doc.element.find(qn("w:body"))
print("section page", doc.sections[0].page_width, doc.sections[0].left_margin, doc.sections[0].right_margin)
content = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin
print("content emu", int(content), "cm", round(content.cm, 3) if hasattr(content, "cm") else content)

# rFonts in docDefaults
from docx.oxml.ns import nsmap
root = doc.element
defaults = root.find(qn("w:settings"))
print("has settings", defaults is not None)
# styles.xml defaults
styles = doc.styles.element
docDefaults = styles.find(qn("w:docDefaults"))
print("docDefaults", docDefaults is not None)
if docDefaults is not None:
    print(docDefaults.xml[:1500])
