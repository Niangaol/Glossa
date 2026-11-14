# -*- coding: utf-8 -*-
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn

p = Path(r"D:\AgentPrograms\PaperTrace\PaperTrace_工程落地计划书.docx")
doc = Document(str(p))

paras = "\n".join(para.text for para in doc.paragraphs)
tables = []
for t in doc.tables:
    rows = []
    for row in t.rows:
        rows.append(" | ".join(c.text.replace("\n", " ") for c in row.cells))
    tables.append("\n".join(rows))
all_text = paras + "\n" + "\n".join(tables)

needles = [
    "S1", "S12", "qwen2.5-coder:7b", "qwen2.5-coder:14b",
    "deepwiki-open", "Vaswani", "flash", "MVP-M3lite",
    "A1", "A12", "trace.json", "RTX 5070 Ti",
    "禁止 fork", "判断题", "GQA", "Task 0", "Task 15",
    "PAPERTRACE_LLM", "PAPERTRACE_EMBED", "nomic-embed-text",
    "w_retr", "0.30", "0.50", "0.20", "sigmoid",
    "nanoGPT", "arXiv:1706.03762", "M0", "M3lite",
    "Ollama", "Python 3.11", "torch.fx", "LanceDB",
    "unresolved", "stale", "annotations",
]
print("---NEEDLES (paragraphs+tables)---")
for n in needles:
    print(("OK " if n in all_text else "MISSING "), n)

print("---TABLE T2 S1-S12---")
print(tables[2][:4000])
print("---TABLE T6 env---")
print(tables[6])
print("---TABLE T13 milestones---")
print(tables[13])
print("---TABLE T14 A1-A12---")
print(tables[14][:5000])
print("---TABLE T11 stack---")
print(tables[11])
print("---TABLE T12 CLI---")
print(tables[12])

print("---CAPTIONS---")
for i, para in enumerate(doc.paragraphs):
    if para.text.startswith("图 ") or "图 " in para.text[:6]:
        print(i, para.text[:120])

print("---EMPTY HEADINGS---")
for i, para in enumerate(doc.paragraphs):
    style = para.style.name if para.style else ""
    if style.startswith("Heading") and not para.text.strip():
        print("empty heading", i)
