#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文 Fig. 1 方法主图 —— 同时导出 SVG 与 PDF (矢量)。

为什么不用手写 SVG + cairosvg: cairosvg 在 text-anchor="middle" 下会把每个 <tspan>
重新按锚点定位, 带下标的公式会整体错位; 另外系统字体缺 ∈/∪/下标字形会渲染成方框。
matplotlib 走同一套 Type-1/TrueType 嵌入路径, 文本定位与数学排版都由它负责, 稳定得多。

图要讲的就是论文的核心: 同一批确定性检查, 放在**弃权**位置(实线)是 +5.7,
放在**上游**当过滤器(灰色虚线)是 −2.6~−10.2。
"""
import os
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "pdf.fonttype": 42, "svg.fonttype": "none",
})
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = "paper/figures"
os.makedirs(OUT, exist_ok=True)
FIG_W, FIG_H = 7.15, 2.45
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, 100); ax.set_ylim(0, 33); ax.axis("off")

GREY, DARK, EDGE = "#9a9a9a", "#111111", "#111111"


def box(x, y, w, h, lines, fill="white", lw=1.0, ec=EDGE, sizes=None, colors=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                fc=fill, ec=ec, lw=lw, zorder=2))
    n = len(lines)
    for i, s in enumerate(lines):
        ax.text(x + w / 2, y + h - (h / (n + 1)) * (i + 1), s, ha="center", va="center",
                fontsize=(sizes[i] if sizes else 8.4),
                color=(colors[i] if colors else DARK), zorder=3)


def arrow(p, q, color=EDGE, ls="-", lw=1.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=8,
                                 lw=lw, color=color, linestyle=ls, zorder=1,
                                 shrinkA=0, shrinkB=0))


# ---- 被否定的上游位置 ----
ax.add_patch(FancyBboxPatch((20, 24.6), 58, 7.6,
                            boxstyle="round,pad=0,rounding_size=0.6",
                            fc="#f5f5f5", ec=GREY, lw=0.9, ls=(0, (4, 2)), zorder=2))
ax.text(49, 30.1, "consumed upstream: re-rank or reject candidates",
        ha="center", va="center", fontsize=8.2, style="italic", color="#666666", zorder=3)
ax.text(49, 27.8, r"$-2.6$ to $-10.2$ Recall@1, no consistent detection gain",
        ha="center", va="center", fontsize=8.2, color="#666666", zorder=3)
ax.text(49, 25.8, "(Table 2a)", ha="center", va="center", fontsize=7.0,
        color=GREY, zorder=3)

# ---- 主链路 ----
box(0.5, 13.0, 12.0, 6.5, ["field", "catalogue"])
box(17.0, 13.0, 15.0, 6.5, ["field card", "no identifiers"], sizes=[8.4, 7.0],
    colors=[DARK, "#444444"])
box(37.0, 13.0, 14.0, 6.5, ["frozen LLM", "matcher"], fill="#ececec")
box(57.5, 10.8, 26.5, 10.6,
    ["abstention score", r"$s(j)=b(j)\,(1-w\sum_{d}V_d)$", "evidence, not filter"],
    fill="#dcdcdc", lw=1.7, sizes=[7.8, 8.4, 6.8], colors=[DARK, DARK, "#333333"])
box(88.5, 13.0, 11.3, 6.5, ["concept", "or UNKNOWN"], sizes=[8.2, 8.0])

arrow((12.5, 16.25), (16.8, 16.25))
arrow((32.0, 16.25), (36.8, 16.25))
arrow((51.0, 16.25), (57.3, 16.25))
ax.text(54.4, 18.5, r"$\hat{c}(j)$", ha="center", va="center", fontsize=7.8)
ax.text(54.2, 13.6, r"$b(j)\!=\!0/1$", ha="center", va="center", fontsize=7.4)
arrow((84.0, 16.25), (88.3, 16.25))
ax.text(86.2, 18.8, r"$s\lessgtr\theta$", ha="center", va="center", fontsize=7.2)

# ---- 确定性检查 ----
box(37.0, 1.6, 42.0, 7.6,
    ["deterministic compatibility checks",
     r"$V_{\mathrm{unit}},\;V_{\mathrm{type}},\;V_{\mathrm{specimen}}\in\{0,\frac{1}{2},1\}$",
     "printable rules; every decision reports its predicate"],
    sizes=[8.0, 8.6, 7.0], colors=[DARK, DARK, "#333333"])

arrow((70.7, 9.2), (70.7, 10.6), lw=1.5)                       # 检查 -> 弃权 (本文)
ax.plot([24.5, 24.5, 37.0], [13.0, 5.4, 5.4], color=EDGE, lw=1.0, zorder=1)
arrow((35.6, 5.4), (36.8, 5.4))                                 # field card -> 检查
ax.plot([44.0, 44.0, 34.5, 34.5], [9.2, 11.0, 11.0, 23.4], color=GREY, lw=1.1,
        ls=(0, (4, 2)), zorder=1)
arrow((34.5, 23.0), (34.5, 24.4), color=GREY, ls=(0, (4, 2)), lw=1.1)
ax.text(36.6, 21.4, r"$\times$", ha="center", va="center", fontsize=11, color=GREY)

fig.savefig(os.path.join(OUT, "method.pdf"), bbox_inches="tight", pad_inches=0.02)
fig.savefig(os.path.join(OUT, "method.svg"), bbox_inches="tight", pad_inches=0.02)
print("-> %s/method.{pdf,svg}" % OUT)
