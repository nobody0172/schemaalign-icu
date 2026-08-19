#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5a · 语义召回 + 确定性门控。

流程:
  1. 在 **MIMIC-IV 验证分割** 上标定 θ_open (C4: 不得在目标域上选)
  2. 用同一个 θ 在三个域上评测, 与四条基线同表对比
  3. 同时跑 hard_reject_prov 的两种口径 (两份规格文档不一致, 用实测决定)
"""
import csv
import json
import os
import sys

sys.path.insert(0, "src")

from schemaalign.gates.rules import FieldSpec
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import calibrate_theta, gated_predict
from schemaalign.match.metrics import evaluate

GOLD, CAT, EMB = "data/gold", "data/field_catalog", "data/embed"
DBS = [("mimic-iv", "field_catalog_m4.csv"), ("mimic-iii", "field_catalog_m3cv.csv"),
       ("eicu", "field_catalog_eicu.csv")]


def concept_representatives():
    """概念代表 = 该概念在 **MIMIC-IV 侧** gold 中行数最多的字段 (C3: 只用源域)。"""
    lab = {c["field_key"]: (c.get("label") or c["field_key"])
           for c in csv.DictReader(open(os.path.join(CAT, "field_catalog_m4.csv"),
                                        newline="", encoding="utf-8"))}
    best = {}
    for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or not r["src_table"] or r["src_table"] == "table_column":
            continue
        n = int(r["n_rows"] or 0)
        if r["base_concept"] not in best or n > best[r["base_concept"]][0]:
            best[r["base_concept"]] = (n, FieldSpec(
                db="mimic-iv", field_key=r["field_key"],
                raw_name=lab.get(r["field_key"], r["field_key"]).split("|")[-1],
                src_table=r["src_table"], unit_observed=r["unit_observed"] or None,
                dtype_inferred="numeric", p01=r["p01"], p50=r["p50"], p99=r["p99"]))
    return {c: v[1] for c, v in best.items()}


if __name__ == "__main__":
    reps = concept_representatives()
    print("概念代表 %d 个" % len(reps))
    rows, thetas = [], {}

    for hrp in (True, False):
        tag = "prov-hard" if hrp else "prov-soft"
        val = load_evalset(GOLD, CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
        th, rec = calibrate_theta(val, EMB, reps, hard_reject_prov=hrp)
        thetas[tag] = {"theta": th, "n_val_fields": len(val),
                       "curve": rec[::5]}
        best = max(rec, key=lambda r: r["F1"])
        print("\n[%s] θ_open 标定于 MIMIC-IV val (%d 字段, %d 正例): θ*=%.2f  (val F1=%.1f, Cov=%.1f)"
              % (tag, len(val), sum(1 for i in val.items if i["gold"]), th,
                 best["F1"], best["Coverage"]))

        for db, fn in DBS:
            es = load_evalset(GOLD, CAT, db, fn,
                              split="test" if db == "mimic-iv" else None)
            pred = gated_predict(es, EMB, reps, theta=th, hard_reject_prov=hrp)
            m = evaluate(es, pred, reps)
            m.update({"method": "Semantic recall + deterministic gate (%s)" % tag,
                      "domain": db, "theta": th})
            rows.append(m)
            print("  %-10s R@1=%5.1f R@10=%5.1f P=%5.1f F1=%5.1f Cov=%5.1f "
                  "UnitViol=%s OpenAUROC=%5.1f  (n=%d, pos=%d)"
                  % (db, m["Recall@1"], m["Recall@10"], m["Precision"], m["F1"],
                     m["Coverage"],
                     ("%.1f" % m["UnitViolRate"]) if m["UnitViolRate"] == m["UnitViolRate"] else "n/a",
                     m["OpenSet_AUROC"], m["n_fields"], m["n_positive"]))

    json.dump(thetas, open(os.path.join(GOLD, "theta_calibration.json"), "w"),
              indent=2, ensure_ascii=False)
    os.makedirs("results/tables", exist_ok=True)
    cols = ["method", "domain", "theta", "Recall@1", "Recall@5", "Recall@10", "Precision",
            "Recall", "F1", "Coverage", "UnitViolRate", "OpenSet_AUROC", "OpenSet_AUPRC",
            "n_fields", "n_positive", "n_unknown"]
    with open("results/tables/table2_gated.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("\n-> results/tables/table2_gated.csv ; θ 标定曲线 -> data/gold/theta_calibration.json")
