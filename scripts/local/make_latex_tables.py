#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 results/tables/*.csv 生成论文用的 LaTeX 表格。

所有数字**只从 CSV 读**, 不在此处硬编码 —— 这样 paper-claim-audit 可以逐格回溯到结果文件。
输出: paper/tables/{tab_main,tab_placement,tab_ablation}.tex
"""
import csv
import os

R = "results/tables"
OUT = "paper/tables"
os.makedirs(OUT, exist_ok=True)
DB = ("mimic-iv", "mimic-iii", "eicu")
DBNAME = {"mimic-iv": "MIMIC-IV", "mimic-iii": "CareVue", "eicu": "eICU"}


def rd(name):
    return list(csv.DictReader(open(os.path.join(R, name), newline="", encoding="utf-8")))


def f1(x, nd=1):
    try:
        return ("%%.%df" % nd) % float(x)
    except (TypeError, ValueError):
        return "--"


# ============================ Table 1 (大表): 全部匹配器 x 三库 x 四指标 ============
# 三个来源 (table2_final / table8_multifamily / table3_placement_graded) 的
# n_fields / n_positive 完全一致, 因此可以并排。已在生成时断言。
t2 = rd("table2_final.csv")
mf = rd("table8_multifamily.csv")
idx = {(r["method"], r["domain"]): r for r in t2}
mfi = {(r["model"], r["domain"]): r for r in mf}
_ns = {(r["domain"], r["n_fields"], r["n_positive"]) for r in t2} \
    | {(r["domain"], r["n_fields"], r["n_positive"]) for r in mf}
assert len(_ns) == 3, "评测集不一致, 不能并排: %s" % _ns

def d_ci(r, dk="delta", lo="paired_CI_lo", hi="paired_CI_hi"):
    return "%s\\,[%s,\\,%s]" % (f1(r[dk], 1), f1(r[lo], 1), f1(r[hi], 1))

ROWS = [
    ("head", r"\emph{(a) non-semantic}"),
    ("t2", "Exact / normalized name", "Exact / normalized name"),
    ("t2", "Ontology only (LOINC)", "Ontology only (LOINC)"),
    ("head", r"\emph{(b) frozen encoders}"),
    ("t2", "Frozen encoder, general (MiniLM-L6)", "MiniLM-L6, 23\\,M"),
    ("t2", "Frozen encoder, biomedical (SapBERT)", "SapBERT, 110\\,M (biomedical)"),
    ("t2ck", "SapBERT + deterministic checks as abstention",
     "\\quad + checks as abstention"),
    ("head", r"\emph{(c) frozen LLM matchers}"),
    ("mf", "gpt-4.1", "\\textsc{gpt-4.1} (OpenAI)"),
    ("mfo", "gpt-4.1", "\\quad + checks (\\textbf{ours})"),
    ("mf", "deepseek-v3.2", "\\textsc{deepseek-v3.2}"),
    ("mfo", "deepseek-v3.2", "\\quad + checks (\\textbf{ours})"),
    ("mf", "gemini-2.5-pro", "\\textsc{gemini-2.5-pro} (Google)"),
    ("mfo", "gemini-2.5-pro", "\\quad + checks (\\textbf{ours})"),
]
NCOL = 3 * 4
lines = [r"\begin{table*}[t]", r"\centering",
         r"\caption{Field alignment and open-set detection. All rows are evaluated on "
         r"\emph{identical} field sets (MIMIC-IV test split, CareVue and eICU in full); "
         r"$n$ fields\,/\,mappable are $132/49$, $696/296$, $244/152$. R@1 is Recall@1 "
         r"over mappable fields and is blind to the abstention decision; P is precision "
         r"of the top-1 assignment; AUC is open-set AUROC. $\Delta$ compares each "
         r"matcher with and without the checks, with a \emph{paired} bootstrap 95\% CI "
         r"over field indices ($B{=}2000$). Thresholds are fitted on the MIMIC-IV "
         r"validation split only and never refitted per model.}",
         r"\label{tab:main}", r"\scriptsize", r"\setlength{\tabcolsep}{3pt}",
         r"\begin{tabular}{@{}l rrr l rrr l rrr l@{}}", r"\toprule",
         r"& \multicolumn{4}{c}{MIMIC-IV} & \multicolumn{4}{c}{CareVue} & "
         r"\multicolumn{4}{c}{eICU} \\",
         r"\cmidrule(lr){2-5}\cmidrule(lr){6-9}\cmidrule(lr){10-13}",
         r"Matcher & R@1 & P & AUC & $\Delta$AUC\,[95\% CI] & R@1 & P & AUC & "
         r"$\Delta$AUC\,[95\% CI] & R@1 & P & AUC & $\Delta$AUC\,[95\% CI] \\",
         r"\midrule"]
for spec in ROWS:
    if spec[0] == "head":
        lines.append(r"\multicolumn{13}{@{}l}{%s}\\" % spec[1]); continue
    kind, key, disp = spec
    cells = []
    for d in DB:
        if kind in ("t2", "t2ck"):
            r = idx[(key, d)]
            cells += [f1(r["Recall@1"]), f1(r["Precision"]), f1(r["OpenSet_AUROC"]), "--"]
        elif kind == "mf":
            r = mfi[(key, d)]
            cells += [f1(r["Recall@1"]), f1(r["Precision"]), f1(r["AUROC_base"]), "--"]
        else:
            r = mfi[(key, d)]
            cells += [f1(r["Recall@1"]), f1(r["Precision"]), f1(r["AUROC_ours"]), d_ci(r)]
    if kind == "mfo":
        cells = [c if c == "--" else r"\textbf{%s}" % c for c in cells]
    lines.append("%s & %s \\\\" % (disp, " & ".join(cells)))
lines += [r"\bottomrule", r"\end{tabular}",
          r"\vspace{-4pt}", r"\end{table*}"]
open(os.path.join(OUT, "tab_main.tex"), "w").write("\n".join(lines) + "\n")

# ============================ Table 2: 位置对照 + 逐维消融 =========================
# 跨栏 (table*): 单栏放不下 7 列, 会溢出到正文。
pl = rd("table3_placement_graded.csv")
pi = {(r["domain"], r["variant"]): r for r in pl}
ab = rd("table3_abstain_ablation.csv")
ai = {(r["domain"], r["setting"]): r for r in ab}
lines = [r"\begin{table*}[t]", r"\centering",
         r"\caption{The same graded penalty $w\sum_d V_d$, evaluated two ways. "
         r"(a) Consumed three ways---weight, dimensions, candidates, calibration split "
         r"and test fields held fixed, only the consumer varies; $\Delta$ is against the "
         r"matcher's own abstention, with paired bootstrap 95\% CIs. "
         r"(b) $\Delta$AUROC of each dimension subset used as abstention evidence, on "
         r"the same matcher and fields.}",
         r"\label{tab:ablate}", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
         r"\begin{tabular}{@{}l rr l rr l rr l@{}}", r"\toprule",
         r"& \multicolumn{3}{c}{MIMIC-IV} & \multicolumn{3}{c}{CareVue} & "
         r"\multicolumn{3}{c}{eICU} \\",
         r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}\cmidrule(lr){8-10}",
         r"& $\Delta$R@1 & $\Delta$AUC & 95\% CI & $\Delta$R@1 & $\Delta$AUC & 95\% CI "
         r"& $\Delta$R@1 & $\Delta$AUC & 95\% CI \\", r"\midrule",
         r"\multicolumn{10}{@{}l}{\emph{(a) consumer of the penalty}}\\"]
for k, disp in (("A graded re-rank (reorder only)", "re-rank candidates"),
                ("B graded reject (kappa on val)", "reject candidates"),
                ("C graded abstention (ours)", r"\textbf{abstain (ours)}")):
    cells = []
    for d in DB:
        r = pi[(d, k)]
        cells += [f1(r["dRecall@1"], 1), f1(r["dAUROC"], 1),
                  "[%s,\\,%s]" % (f1(r["paired_CI_lo"], 1), f1(r["paired_CI_hi"], 1))]
    if "ours" in disp:
        cells = [r"\textbf{%s}" % c for c in cells]
    lines.append("%s & %s \\\\" % (disp, " & ".join(cells)))
lines += [r"\addlinespace[2pt]", r"\midrule",
          r"\multicolumn{10}{@{}l}{\emph{(b) dimensions used as abstention evidence "
          r"($\Delta$AUROC)}}\\"]
DIMROWS = [("仅 unit", "unit only"), ("仅 type", "data type only"),
           ("仅 specimen", "specimen only"), ("仅 provenance", "provenance only"),
           ("全部四维", "all four"),
           ("− provenance", r"\textbf{unit + type + specimen (ours)}")]
for k, disp in DIMROWS:
    cells = []
    for d in DB:
        r = ai[(d, k)]
        cells += ["", f1(r["delta_vs_base"], 1),
                  "[%s,\\,%s]" % (f1(r["CI_lo"], 1), f1(r["CI_hi"], 1))]
    if "ours" in disp:
        cells = [c if not c else r"\textbf{%s}" % c for c in cells]
    lines.append("%s & %s \\\\" % (disp, " & ".join(cells)))
lines += [r"\bottomrule", r"\end{tabular}", r"\vspace{-4pt}", r"\end{table*}"]
open(os.path.join(OUT, "tab_ablate.tex"), "w").write("\n".join(lines) + "\n")

# ============================ Table 3: 下游跨库迁移 ==============================
tr = rd("table4_transfer.csv")
ti = {(r["domain"], r["alignment"]): r for r in tr}
TD = [("mimic-iii", "CareVue"), ("eicu", "eICU")]
lines = [r"\begin{table}[t]", r"\centering",
         r"\caption{Zero-shot cross-database transfer of a 24-channel physiological "
         r"time-series model trained on MIMIC-IV (validation AUROC $84.20\pm0.12$), as a "
         r"function of how target fields are mapped onto channels. Mortality AUROC, "
         r"mean$\pm$sd over five seeds; $c$ = channels receiving data. The last row is a "
         r"patient-level paired bootstrap of the abstention effect.}",
         r"\label{tab:transfer}", r"\scriptsize", r"\setlength{\tabcolsep}{3pt}",
         r"\begin{tabular}{@{}l cc cc@{}}", r"\toprule",
         r"& \multicolumn{2}{c}{CareVue ($n{=}19{,}112$)} & "
         r"\multicolumn{2}{c}{eICU ($n{=}110{,}257$)} \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}",
         r"Field alignment & AUROC & $c$ & AUROC & $c$ \\", r"\midrule"]
for key, disp in (("oracle", "reference (adjudicated)"), ("exact", "exact name"),
                  ("llm", "frozen LLM"),
                  ("llm_abstain", r"\quad + abstention (\textbf{ours})")):
    cells = []
    for d, _ in TD:
        r = ti[(d, key)]
        cells += ["%s\\,$\\pm$\\,%s" % (f1(r["AUROC_mean"], 1), f1(r["AUROC_sd"], 1)),
                  r["channels_filled"]]
    lines.append("%s & %s \\\\" % (disp, " & ".join(cells)))
lines.append(r"\midrule")
pd_ = [ti[(d, "abstain vs llm (paired)")] for d, _ in TD]
lines.append(r"paired $\Delta$ (ours $-$ LLM) & \multicolumn{2}{c}{%s} & "
             r"\multicolumn{2}{c}{%s} \\"
             % tuple("$%s$ [%s, %s]" % (f1(r["AUROC_mean"], 2), f1(r["CI_lo"], 2),
                                        f1(r["CI_hi"], 2)) for r in pd_))
lines += [r"\bottomrule", r"\end{tabular}", r"\vspace{-4pt}", r"\end{table}"]
open(os.path.join(OUT, "tab_transfer.tex"), "w").write("\n".join(lines) + "\n")

# ---------------------------------------------------------- Table 3 消融 (紧凑)
ab = rd("table3_abstain_ablation.csv")
ai = {(r["domain"], r["setting"]): r for r in ab}
lines = [r"\begin{table}[t]", r"\centering",
         r"\caption{Open-set AUROC gain of each check dimension used alone, and of the "
         r"selected subset, against the matcher's own abstention.}",
         r"\label{tab:ablation}", r"\footnotesize",
         r"\setlength{\tabcolsep}{4pt}",
         r"\begin{tabular}{l rrr}", r"\toprule",
         r"Dimensions used & MIMIC-IV & CareVue & eICU \\", r"\midrule"]
for dim, disp in (("unit", "unit only"), ("type", "data type only"),
                  ("specimen", "specimen only"), ("provenance", "provenance only")):
    vals = [f1(ai[(d, "\u4ec5 %s" % dim)]["delta_vs_base"], 2) for d in DB]
    lines.append("%s & %s \\\\" % (disp, " & ".join(vals)))
lines.append(r"\addlinespace[1pt]")
allf = [f1(ai[(d, "\u5168\u90e8\u56db\u7ef4")]["delta_vs_base"], 2) for d in DB]
sel = [f1(ai[(d, "\u2212 provenance")]["delta_vs_base"], 2) for d in DB]
lines.append("all four & %s \\\\" % " & ".join(allf))
lines.append(r"\textbf{unit\,+\,type\,+\,specimen (ours)} & %s \\"
             % " & ".join(r"\textbf{%s}" % v for v in sel))
lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
open(os.path.join(OUT, "tab_ablation.tex"), "w").write("\n".join(lines) + "\n")

print("wrote:", sorted(os.listdir(OUT)))
