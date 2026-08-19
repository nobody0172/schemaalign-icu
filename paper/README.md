# Knowing When Not to Match: Open-Set Field Alignment across ICU Databases

ICASSP 2027 投稿的完整 LaTeX 源码。

## 文件

| 文件 | 说明 |
|---|---|
| `main.tex` | 主文件：标题、作者、摘要、Index Terms、致谢、伦理声明、参考文献入口 |
| `sections/01_intro.tex` | 1. Introduction（含相关工作与三条贡献） |
| `sections/02_method.tex` | 2. Method（2.1 Field Cards / 2.2 Checks / 2.3 Abstention Score / 2.4 Calibration） |
| `sections/03_experiments.tex` | 3. Experiments（3.1–3.5） |
| `sections/04_conclusions.tex` | 4. Conclusions |
| `tables/tab_main.tex` | Table 1（跨栏）全部匹配器 × 三库 × 四指标 |
| `tables/tab_ablate.tex` | Table 2（跨栏）惩罚的消费方式 + 逐维消融 |
| `tables/tab_transfer.tex` | Table 3 下游跨库迁移 |
| `figures/method.pdf` | Fig. 1 方法总架构图（矢量，正文引用的就是它） |
| `figures/method.svg` | 同一张图的 SVG 源（可编辑） |
| `references.bib` | 16 条参考文献 |
| `spconf.sty` / `IEEEbib.bst` | **ICASSP 官方样式文件**，取自官方 paper kit |
| `main_reference.pdf` | 已编译好的 PDF，供比对 |

## 编译

三种方式任选：

```bash
tectonic -X compile main.tex
```

```bash
latexmk -pdf main.tex
```

```bash
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

> 用的是 `\documentclass{article}` + `spconf.sty`，不是 `IEEEtran`。
> ICASSP 的官方模板就是这一套，不要换成 IEEEtran。

## 版面规则（ICASSP CFP）

正文（含图表与参考文献）**最多 4 页**；可选的第 5 页**只能**放参考文献、经费致谢和
Compliance with Ethical Standards 声明。

当前版本为 **7 页**，是在"暂不限制篇幅、先定结构"的前提下排的，**投稿前需要压缩**。
可压缩的余量按代价从低到高：

1. Table 1 的 (b) 组编码器行只保留 SapBERT（省约 3 行）
2. Table 2 的 95% CI 列并进 Δ 列（省约 1/3 表宽，可改回单栏）
3. Fig. 1 由跨栏改单栏
4. 3.3 与 3.4 的行文精简

## 表格与图的来源

**表格里的每一个数字都由脚本从结果文件生成，不是手写的**：

- `scripts/local/make_latex_tables.py` ← `results/tables/*.csv`
- `scripts/local/make_method_figure.py` → `figures/method.{pdf,svg}`

改了实验就重跑这两个脚本，表和图会自动更新；不要直接手改 `tables/*.tex`。
`results/tables/paper_constants.csv` 记录了正文里每个标量的来源文件。

## 作者

（匿名评审版本已隐去作者信息）
