#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心实验：把确定性门控**叠加在最强语义排序器之上**。

论文的中心主张是「语义相似度负责召回, 确定性检查负责接受」——
匹配覆盖率分析 (table2_coverage_curve.csv) 已证明**最强的排序器是 Name-embedding**,
而不是我们训练的 facet 模块。因此该主张的正确检验方式是:
  **保留最强排序器, 只在其上加门控**, 看能否在几乎不损失排序质量的前提下
  把单位冲突率压到 0 并获得可用的 UNKNOWN 判定。

这既是最诚实的实验设计, 也是唯一能让门控的贡献单独可见的设计。
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
exec(open("scripts/local/run_table2.py").read().split("if __name__")[0])
from schemaalign.gates.rules import gate_all                       # noqa: E402
from schemaalign.match.gated import _spec, _stat_sim               # noqa: E402


def gate_on_top(es, base_raw, lam=(1.0, 1.0, 0.5), gamma=0.0, use_gate=True):
    """base_raw: {field: [(score, concept)]} 来自任意排序器。返回重排后的 raw。"""
    out = {}
    for it in es.items:
        cand = base_raw.get(it["field_key"], [])
        fs = _spec(it["row"], it["field_key"])
        keep = []
        for s, c in cand:
            rep = REPS.get(c)
            if use_gate and rep is not None:
                g = gate_all(fs, rep, concept_mode=True)
                if g.hard_reject:
                    continue
                s = (s + gamma * _stat_sim(fs, rep)
                     - lam[0] * g.v_unit - lam[1] * g.v_type - lam[2] * g.v_prov)
            keep.append((s, c))
        keep.sort(key=lambda x: -x[0])
        out[it["field_key"]] = keep
    return out


def curve(es, raw):
    allsc = sorted({v[0][0] for v in raw.values() if v}, reverse=True)
    pts = []
    for th in allsc[:: max(1, len(allsc) // 200)] + [-1e9]:
        pred = {k: ([c for _, c in v] if v and v[0][0] >= th else []) for k, v in raw.items()}
        conf = {k: (v[0][0] if v else -1e9) for k, v in raw.items()}
        m = evaluate(es, pred, REPS, conf=conf)
        pts.append((m["Coverage"], m["Precision"], m["UnitViolRate"], m["OpenSet_AUROC"]))
    return sorted(pts)


def at_cov(pts, t, i=1):
    ok = [p for p in pts if p[0] >= t]
    return min(ok, key=lambda p: p[0])[i] if ok else None


if __name__ == "__main__":
    T = [20, 30, 40, 50]
    rows = []
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None),
                       ("eicu", "field_catalog_eicu.csv", None)):
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        base = _emb_scores(es, "name")
        print("\n=== %s (n=%d, 正例 %d) ===" % (db, len(es), sum(1 for i in es.items if i["gold"])))
        print("%-34s %s | %s | %s" % ("设置",
              " ".join("P@C%d" % t for t in T),
              " ".join("UV@C%d" % t for t in T), "OpenAUROC"))
        for nm, raw in (("Name-emb (无门控)", gate_on_top(es, base, use_gate=False)),
                        ("Name-emb + 确定性门控", gate_on_top(es, base, use_gate=True))):
            pts = curve(es, raw)
            conf = {k: (v[0][0] if v else -1e9) for k, v in raw.items()}
            allp = {k: [c for _, c in v] for k, v in raw.items()}
            auroc = evaluate(es, allp, REPS, conf=conf)["OpenSet_AUROC"]
            ps = [at_cov(pts, t, 1) for t in T]
            uv = [at_cov(pts, t, 2) for t in T]
            f = lambda xs: " ".join(("%5.1f" % x) if x is not None and x == x else "  n/a" for x in xs)
            print("%-34s %s | %s | %8.1f" % (nm, f(ps), f(uv), auroc))
            rows.append({"domain": db, "setting": nm, "OpenSet_AUROC": round(auroc, 2),
                         **{"P@Cov%d" % t: (round(v, 2) if v is not None else "") for t, v in zip(T, ps)},
                         **{"UnitViol@Cov%d" % t: (round(v, 2) if v is not None and v == v else "")
                            for t, v in zip(T, uv)}})
    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table3_gate_ontop.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("\n-> results/tables/table3_gate_ontop.csv")
