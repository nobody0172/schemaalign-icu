#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精度—覆盖曲线：在**匹配覆盖率**下比较各方法。

为什么必须这样比:
  单点 F1 是在「各方法各自 F1 最优的 θ」上取的, 而 val 只有 61 个字段, θ 估计噪声大。
  基线是「极高精度 + 极低覆盖」(Exact: P=100, Cov=13.8), 本方法是「较高覆盖 + 较低精度」——
  **这是工作点差异, 不是质量差异**。正确做法是扫遍 θ, 报 Precision@matched-Coverage
  与 AUC(precision-coverage)。
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
exec(open("scripts/local/run_table2.py").read().split("if __name__")[0])
from schemaalign.match.facet_match import facet_predict          # noqa: E402
from schemaalign.match.gated import gated_predict                # noqa: E402

NAMES = json.load(open("data/t5b/meta_K10_l0.20.json"))["concepts"]


def raw_scores(es, which):
    if which == "name":
        return _emb_scores(es, "name")
    if which == "card":
        return _emb_scores(es, "card")
    if which == "t5a":
        return gated_predict(es, EMB, REPS, theta=None, return_scores=True)[1]
    if which == "t5b":
        return facet_predict(es, "data/t5b", NAMES, REPS, use_gate=False,
                             theta=None, return_scores=True)[1]
    if which == "t5b_gate":
        return facet_predict(es, "data/t5b", NAMES, REPS, use_gate=True,
                             theta=None, return_scores=True)[1]
    raise ValueError(which)


METHODS = [("Name embedding (frozen)", "name"),
           ("FieldCard embedding, no gate", "card"),
           ("Semantic recall + gate (T5a)", "t5a"),
           ("Facet (T5b, no gate)", "t5b"),
           ("SchemaAlign-ICU (T5b + gate)", "t5b_gate")]
TARGETS = [10, 20, 30, 40, 50]


def curve(es, raw):
    """扫 θ -> [(coverage, precision, recall@1, f1)]"""
    allsc = sorted({v[0][0] for v in raw.values() if v}, reverse=True)
    pts = []
    for th in allsc[:: max(1, len(allsc) // 200)] + [-1e9]:
        pred = {k: ([c for _, c in v] if v and v[0][0] >= th else []) for k, v in raw.items()}
        m = evaluate(es, pred, REPS)
        pts.append((m["Coverage"], m["Precision"], m["Recall@1"], m["F1"]))
    return sorted(pts)


def at_coverage(pts, target):
    """线性插值取指定覆盖率下的精度; 覆盖率达不到则返回 None。"""
    ok = [p for p in pts if p[0] >= target]
    return min(ok, key=lambda p: p[0])[1] if ok else None


if __name__ == "__main__":
    out = []
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None),
                       ("eicu", "field_catalog_eicu.csv", None)):
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        print("\n=== %s (n=%d, 正例 %d) ===" % (db, len(es), sum(1 for i in es.items if i["gold"])))
        print("%-32s %s   %8s" % ("方法", "  ".join("P@Cov%d" % t for t in TARGETS), "曲线AUC"))
        for nm, key in METHODS:
            pts = curve(es, raw_scores(es, key))
            vals = [at_coverage(pts, t) for t in TARGETS]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            auc = float(np.trapezoid(ys, xs) / max(1e-9, max(xs) - min(xs))) if len(xs) > 1 else 0.0
            print("%-32s %s   %8.1f" % (nm, "  ".join(
                ("%7.1f" % v) if v is not None else "    n/a" for v in vals), auc))
            out.append({"domain": db, "method": nm, "curve_auc": round(auc, 2),
                        **{"P@Cov%d" % t: (round(v, 2) if v is not None else "")
                           for t, v in zip(TARGETS, vals)}})
    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table2_coverage_curve.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0].keys())); w.writeheader(); w.writerows(out)
    print("\n-> results/tables/table2_coverage_curve.csv")
