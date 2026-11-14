# -*- coding: utf-8 -*-
"""PaperTrace plan figures via Pillow (bundled env has no matplotlib)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W = 1260

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def font(size, bold=False):
    paths = FONT_CANDIDATES[:]
    if bold:
        paths = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"] + paths
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F14B = font(24, True)
F12 = font(20)
F11 = font(18)
F10 = font(16)
F9 = font(15)

ACCENT = (31, 78, 121)
INK = (26, 26, 26)
MUTED = (92, 92, 92)
WHITE = (255, 255, 255)
RED = (161, 38, 38)
GREEN = (46, 125, 79)
ORANGE = (196, 123, 22)
PURPLE = (107, 63, 160)


def new(h):
    img = Image.new("RGB", (W, h), WHITE)
    return img, ImageDraw.Draw(img)


def round_rect(draw, xy, fill, outline, r=18, width=2):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def center_text(draw, box, lines, fnt, fill=INK, gap=6):
    x0, y0, x1, y1 = box
    heights, widths = [], []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + gap * (len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) / 2
    cx = (x0 + x1) / 2
    for line, tw, th in zip(lines, widths, heights):
        draw.text((cx - tw / 2, y), line, font=fnt, fill=fill)
        y += th + gap


def arrow_down(draw, x, y1, y2):
    if y2 - y1 < 16:
        return
    draw.line((x, y1, x, y2 - 8), fill=ACCENT, width=3)
    draw.polygon([(x - 7, y2 - 12), (x + 7, y2 - 12), (x, y2)], fill=ACCENT)


def arrow_right(draw, x1, y, x2):
    if x2 - x1 < 16:
        return
    draw.line((x1, y, x2 - 8, y), fill=ACCENT, width=3)
    draw.polygon([(x2 - 12, y - 7), (x2 - 12, y + 7), (x2, y)], fill=ACCENT)


def arrow_left(draw, x1, y, x2):
    """Arrow pointing left, from x1 (right) to x2 (left)."""
    if x1 - x2 < 16:
        return
    draw.line((x1, y, x2 + 8, y), fill=ACCENT, width=3)
    draw.polygon([(x2 + 12, y - 7), (x2 + 12, y + 7), (x2, y)], fill=ACCENT)


def save(img, name):
    png = OUT / f"{name}.png"
    img.save(png, "PNG")
    print("wrote", png, img.size)


def fig1():
    img, d = new(740)
    d.text((W // 2, 16), "两条输入解耦，先代码后论文", font=F14B, fill=ACCENT, anchor="mt")

    round_rect(d, (50, 64, 370, 168), (238, 246, 240), GREEN)
    center_text(d, (50, 64, 370, 168), ["代码仓库", "PyTorch / 本地或 git"], F12)

    round_rect(d, (890, 64, 1210, 168), (244, 247, 251), ACCENT)
    center_text(d, (890, 64, 1210, 168), ["论文", "arXiv TeX 优先，PDF 兜底"], F12)

    arrow_down(d, 210, 168, 205)
    arrow_down(d, 1050, 168, 205)

    round_rect(d, (50, 210, 370, 340), (238, 246, 240), GREEN)
    center_text(d, (50, 210, 370, 340), ["1  算子图", "fx 主路径 · 关 flash"], F11)

    round_rect(d, (445, 210, 815, 340), (255, 248, 232), ORANGE)
    center_text(d, (445, 210, 815, 340), ["3  符号三元", "D = n_embd = 768"], F11)

    round_rect(d, (890, 210, 1210, 340), (244, 247, 251), ACCENT)
    center_text(d, (890, 210, 1210, 340), ["2  公式项", "稳定 ID + 拆项"], F11)

    arrow_right(d, 370, 275, 445)
    arrow_left(d, 890, 275, 815)

    arrow_down(d, 530, 340, 385)
    arrow_down(d, 730, 340, 385)

    round_rect(d, (80, 390, 560, 515), (251, 243, 232), ORANGE)
    center_text(d, (80, 390, 560, 515), ["4  三步对齐", "检索 -> 判断题 -> 加权"], F11)

    round_rect(d, (700, 390, 1180, 515), (247, 240, 248), PURPLE)
    center_text(d, (700, 390, 1180, 515), ["5  对账 + L0-L3", "trace.json 唯一契约"], F11)

    arrow_down(d, 320, 515, 560)
    arrow_down(d, 940, 515, 560)

    round_rect(d, (220, 565, 1040, 700), (232, 238, 246), ACCENT)
    center_text(d, (220, 565, 1040, 700), ["单文件 HTML 播放器  +  trace.json"], F12)
    save(img, "fig1_pipeline")


def fig2():
    img, d = new(500)
    d.text((W // 2, 16), "对齐引擎硬规则", font=F14B, fill=ACCENT, anchor="mt")
    steps = [
        (40, "1  双向检索", ["LanceDB Top-5", "代码 对 公式项"], (232, 241, 250)),
        (440, "2  判断题", ["只能 yes / no", "依据不超过 40 字"], (255, 244, 224)),
        (840, "3  结构加权", ["c = sigmoid(w · s)", "绿 / 黄 / 不连线"], (239, 231, 246)),
    ]
    for x, title, body, fc in steps:
        round_rect(d, (x, 70, x + 380, 330), fc, ACCENT)
        d.text((x + 190, 100), title, font=F14B, fill=ACCENT, anchor="mt")
        center_text(d, (x, 150, x + 380, 310), body, F12)
    arrow_right(d, 420, 200, 438)
    arrow_right(d, 820, 200, 838)
    d.text((W // 2, 370), "禁止：一个 prompt 让模型直接生成「公式 -> 行号」映射",
           font=F11, fill=RED, anchor="mt")
    d.text((W // 2, 430), "判断题的错误可解释，生成题的错误不可解释。",
           font=F10, fill=MUTED, anchor="mt")
    save(img, "fig2_align")


def fig3():
    img, d = new(620)
    d.text((W // 2, 16), "12GB 显存怎么分（RTX 5070 Ti Laptop）", font=F14B, fill=ACCENT, anchor="mt")

    def bar(y, title, segs):
        d.text((40, y), title, font=F12, fill=INK)
        x = 40
        scale = 1100 / 12.0
        by = y + 38
        for gb, label, color, tfill in segs:
            w = int(gb * scale)
            d.rectangle((x, by, x + w, by + 92), fill=color)
            if w > 120:
                center_text(d, (x, by, x + w, by + 92), [label, f"{gb:g} GB"], F11, fill=tfill)
            x += w
        d.text((1160, by + 46), "12 GB", font=F10, fill=MUTED, anchor="lm")

    bar(78, "规格默认 14B Q4 + GPU 探针  ->  会挤爆", [
        (9.0, "14B Q4", (180, 35, 24), WHITE),
        (2.2, "探针", (247, 144, 9), WHITE),
        (0.8, "系统", (152, 162, 179), WHITE),
    ])
    bar(270, "本计划默认 7B Q4，探针走 CPU", [
        (5.2, "7B Q4", (2, 122, 72), WHITE),
        (0.8, "向量", (18, 183, 106), WHITE),
        (6.0, "余量 / 系统", (208, 213, 221), INK),
    ])
    d.text((W // 2, 490), "判断题是 yes/no，7B 足够。14B 仅在「只对齐、不跑 forward」时可选。",
           font=F10, fill=MUTED, anchor="mt")
    d.text((W // 2, 540), "本机实测：总量 12227 MiB。Ollama 当时未安装，系统 Python 是 3.13.15。",
           font=F9, fill=MUTED, anchor="mt")
    save(img, "fig3_vram")


def fig4():
    img, d = new(650)
    d.text((W // 2, 16), "里程碑依赖：先代码侧闭环，再接论文", font=F14B, fill=ACCENT, anchor="mt")
    items = [
        ("M0", "环境", (232, 238, 246)),
        ("M1a", "算子图", (217, 240, 227)),
        ("M1b", "符号", (217, 240, 227)),
        ("M2", "播放器", (232, 238, 246)),
        ("M2.5", "缓存", (255, 244, 224)),
        ("M3", "对齐", (243, 232, 255)),
        ("M4", "对账", (243, 232, 255)),
        ("M5", "导出", (232, 238, 246)),
    ]
    gap = 8
    bw = (W - 80 - gap * 7) // 8
    y0, y1 = 70, 220
    xs = []
    for i, (code, name, fc) in enumerate(items):
        x = 40 + i * (bw + gap)
        xs.append(x)
        round_rect(d, (x, y0, x + bw, y1), fc, ACCENT, r=14)
        center_text(d, (x, y0, x + bw, y1), [code, name], F11)
        if i:
            arrow_right(d, xs[i - 1] + bw, (y0 + y1) // 2, x)
    round_rect(d, (40, 270, 620, 440), (244, 247, 251), ACCENT)
    center_text(d, (40, 270, 620, 440), ["代码侧可单独演示", "M0-M2.5：关 flash 的 nanoGPT 图 + L0-L2"], F12)
    round_rect(d, (660, 270, 1220, 440), (251, 243, 232), ORANGE)
    center_text(d, (660, 270, 1220, 440), ["接论文之后才有「对账」", "M3-M5：Vaswani 公式项 对 源码"], F12)
    d.text((W // 2, 490), "兼职日历约 6-8 周。必须 3 周交差则停在 MVP-M3lite，禁止用假数据齐活。",
           font=F10, fill=MUTED, anchor="mt")
    d.text((W // 2, 545), "M2.5 必须插在 M3 之前：分层与缓存一旦定错，接论文后返工最贵。",
           font=F10, fill=MUTED, anchor="mt")
    save(img, "fig4_milestones")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    fig4()
