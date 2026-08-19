#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文主表：确定性门控叠加在最强语义排序器之上。

**λ 必须与打分尺度匹配**（本项目最关键的一个实现细节）:
  余弦分数落在 [0,1], top1-top2 的典型间距只有 0.068,
  而规格里的 λ=1.0 会让 V_unit=0.5 产生 0.5 的惩罚 —— **是候选间距的 7 倍**,
  语义信号被完全淹没 (CareVue P@Cov30 从 83.6 崩到 51.5)。
  λ 与 θ 一律在 **MIMIC-IV 验证分割** 上标定 (C4)。
"""
import csv
import importlib.util
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
_s = importlib.util.spec_from_file_location("got", "scripts/local/run_gate_ontop.py")
G = importlib.util.module_from_spec(_s); _s.loader.exec_module(G)

DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
COVS = [20, 30, 40, 50]


def calib_lambda(grid=(0.0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0)):
    """C4: 在 MIMIC-IV val 上选 λ, 目标 = 单位冲突为 0 的前提下 P@Cov30 最大。"""
    val = G.load_evalset(G.GOLD, G.CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
    base = G._emb_scores(val, "name")
    rec, best = [], (None, -1)
    for sc in grid:
        raw = G.gate_on_top(val, base, lam=(sc, sc, sc * 0.5), use_gate=(sc > 0))
        pts = G.curve(val, raw)
        p = G.at_cov(pts, 30, 1); u = G.at_cov(pts, 30, 2)
        u = 0.0 if (u is None or u != u) else u
        rec.append({"lambda": sc, "P@Cov30": p, "UnitViol@Cov30": u})
        if p is not None and u == 0.0 and p > best[1]:
            best = (sc, p)
    return best[0], rec


if __name__ == "__main__":
    lam, rec = calib_lambda()
    print("λ 标定于 MIMIC-IV val (C4): λ* = %.2f" % lam)
    print("  候选:", ", ".join("λ=%.2f→P%.0f/UV%.0f" % (r["lambda"], r["P@Cov30"] or 0,
                                                        r["UnitViol@Cov30"]) for r in rec))
    rows = []
    for db, fn, sp in DBS:
        es = G.load_evalset(G.GOLD, G.CAT, db, fn, split=sp)
        base = G._emb_scores(es, "name")
        print("\n=== %s (n=%d, 正例 %d) ===" % (db, len(es), sum(1 for i in es.items if i["gold"])))
        print("%-30s %s | %s | %s" % ("设置", " ".join("P@C%d" % c for c in COVS),
                                      " ".join("UV@C%d" % c for c in COVS), "OpenAUROC"))
        for nm, kw in (("语义排序 (无门控)", dict(use_gate=False)),
                       ("+ 确定性门控 (λ*=%.2f)" % lam,
                        dict(use_gate=True, lam=(lam, lam, lam * 0.5)))):
            raw = G.gate_on_top(es, base, **kw)
            pts = G.curve(es, raw)
            conf = {k: (v[0][0] if v else -1e9) for k, v in raw.items()}
            au = G.evaluate(es, {k: [c for _, c in v] for k, v in raw.items()},
                            G.REPS, conf=conf)["OpenSet_AUROC"]
            ps = [G.at_cov(pts, c, 1) for c in COVS]
            uv = [G.at_cov(pts, c, 2) for c in COVS]
            f = lambda xs: " ".join(("%5.1f" % x) if x is not None and x == x else "  n/a"
                                    for x in xs)
            print("%-30s %s | %s | %8.1f" % (nm, f(ps), f(uv), au))
            rows.append({"domain": db, "setting": nm, "lambda": kw.get("lam", ("-",))[0],
                         "OpenSet_AUROC": round(au, 2),
                         **{"P@Cov%d" % c: (round(v, 2) if v is not None else "")
                            for c, v in zip(COVS, ps)},
                         **{"UnitViol@Cov%d" % c: (round(v, 2) if v is not None and v == v else "")
                            for c, v in zip(COVS, uv)}})
    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table_main.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump({"lambda_star": lam, "grid": rec},
              open("data/gold/lambda_calibration.json", "w"), indent=2, ensure_ascii=False)
    print("\n-> results/tables/table_main.csv ; λ 标定 -> data/gold/lambda_calibration.json")
