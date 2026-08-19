#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文图：Fig.2（开放集 ROC + UNKNOWN 占比分层）。Fig.1 框架图另行绘制。"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, "src")
exec(open("scripts/local/run_paper_tables.py").read().split("if __name__")[0])
from schemaalign.match.abstain import abstain_scores  # noqa: E402

CFG = json.load(open("data/gold/abstain_config.json"))
DIMSEL, W = tuple(CFG["dims"]), CFG["w"]
os.makedirs("results/figures", exist_ok=True)


def roc(scores, labels):
    o = np.argsort(-np.asarray(scores))
    l = np.asarray(labels)[o]
    tp = np.cumsum(l); fp = np.cumsum(1 - l)
    P, N = l.sum(), len(l) - l.sum()
    return np.r_[0, fp / max(N, 1)], np.r_[0, tp / max(P, 1)]


fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.3))
NAMES = {"mimic-iv": "MIMIC-IV", "mimic-iii": "MIMIC-III (CareVue)", "eicu": "eICU-CRD"}
for ax, (db, fn, sp) in zip(axes, DBS):
    es = load_evalset(GOLD, CAT, db, fn, split=sp)
    pred = llm_pred(es, db, sp)
    lab = [1 if i["gold"] is not None else 0 for i in es.items]
    b = abstain_scores(es.items, pred, REPS, _spec, dims=())
    s = abstain_scores(es.items, pred, REPS, _spec, w=W, dims=DIMSEL)
    for tag, sc, st in (("LLM abstention only", b, "--"),
                        ("+ deterministic checks", s, "-")):
        x, y = roc([sc[i["field_key"]] for i in es.items], lab)
        from schemaalign.match.abstain import auroc
        a = auroc([sc[i["field_key"]] for i in es.items], lab)
        ax.plot(x, y, st, lw=1.8, label="%s (AUC %.1f)" % (tag, 100 * a))
    ax.plot([0, 1], [0, 1], ":", c="0.6", lw=0.8)
    ax.set_title(NAMES[db], fontsize=10)
    ax.set_xlabel("False positive rate", fontsize=9)
    ax.legend(fontsize=7, loc="lower right", frameon=False)
    ax.tick_params(labelsize=8)
axes[0].set_ylabel("True positive rate", fontsize=9)
plt.tight_layout()
plt.savefig("results/figures/fig2_openset_roc.pdf", bbox_inches="tight")
plt.savefig("results/figures/fig2_openset_roc.png", dpi=180, bbox_inches="tight")
print("-> results/figures/fig2_openset_roc.{pdf,png}")

# 附图：UNKNOWN 占比按覆盖率分层（支撑 C3 的 77.1%）
fig2, ax = plt.subplots(figsize=(4.2, 3.0))
bins = [(0.05, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 0.7), (0.7, 1.01)]
gold = {(r["db"], r["field_key"]) for r in csv.DictReader(
    open(os.path.join(GOLD, "gold_pairs.csv"), newline="", encoding="utf-8"))}
unk = {(r["db"], r["field_key"]) for r in csv.DictReader(
    open(os.path.join(GOLD, "unknown_set_adjudicated.csv"), newline="", encoding="utf-8"))}
CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}
for db, fn in CATF.items():
    xs, ys = [], []
    for lo, hi in bins:
        n_g = n_u = 0
        for r in csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")):
            c = float(r["coverage"] or 0)
            if not (lo <= c < hi):
                continue
            if (db, r["field_key"]) in gold:
                n_g += 1
            elif (db, r["field_key"]) in unk:
                n_u += 1
        if n_g + n_u >= 10:
            xs.append("%d–%d%%" % (lo * 100, hi * 100))
            ys.append(100.0 * n_u / (n_g + n_u))
    ax.plot(xs, ys, "o-", lw=1.6, ms=4, label=NAMES[db])
ax.set_ylabel("fields with no canonical concept (%)", fontsize=8)
ax.set_xlabel("field coverage (fraction of ICU stays)", fontsize=8)
ax.set_ylim(0, 100); ax.tick_params(labelsize=7)
ax.legend(fontsize=7, frameon=False)
plt.tight_layout()
plt.savefig("results/figures/fig3_unknown_by_coverage.pdf", bbox_inches="tight")
plt.savefig("results/figures/fig3_unknown_by_coverage.png", dpi=180, bbox_inches="tight")
print("-> results/figures/fig3_unknown_by_coverage.{pdf,png}")
