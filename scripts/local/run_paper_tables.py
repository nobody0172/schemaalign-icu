#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文主表与消融（B 方案）。见 docs/plans/PAPER_SPEC_v2_openset.md §4。"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import parse_mappings
from schemaalign.gates.rules import FieldSpec
from schemaalign.match.abstain import DIMS, abstain_scores, auroc, bootstrap_ci
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import _spec
from schemaalign.match.metrics import evaluate

GOLD, CAT, EMB = "data/gold", "data/field_catalog", "data/embed"
# 消融必须与主结果用**同一个** w, 否则两张表不可比 (审计发现: 此前消融用了默认 w=0.2,
# 主结果用标定出的 w=0.1, 导致「ours」这一行在两张表里数字不同)。
W = json.load(open(os.path.join(GOLD, "abstain_config.json")))["w"]
DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))


def reps():
    m4 = {c["field_key"]: c for c in csv.DictReader(
        open(os.path.join(CAT, "field_catalog_m4.csv"), newline="", encoding="utf-8"))}
    best = {}
    for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or r["src_table"] in ("", "table_column"):
            continue
        n = int(r["n_rows"] or 0); c = r["base_concept"]; row = m4.get(r["field_key"], {})
        if c not in best or n > best[c][0]:
            best[c] = (n, FieldSpec(
                db="mimic-iv", field_key=r["field_key"],
                raw_name=(row.get("label") or r["field_key"]).split("|")[-1],
                src_table=r["src_table"], unit_observed=r["unit_observed"] or None,
                dtype_inferred="numeric", p01=r["p01"], p50=r["p50"], p99=r["p99"],
                dtype_declared=bool((row.get("param_type") or "").strip()),
                specimen=row.get("specimen") or None))
    return {k: v[1] for k, v in best.items()}


REPS = reps()


def llm_pred(es, db, sp):
    raw = json.load(open("data/llm_baseline/direct_%s_%s.json" % (db, sp or "all")))
    valid = set(es.concepts); pred = {}
    for k, v in raw.items():
        if k == "_usage":
            continue
        mp = parse_mappings(v["text"])
        for fk, l, t in zip(v["keys"], v["labels"], v["tables"]):
            hit = mp.get("%s.%s" % (t, l)) or mp.get(l) or []
            pred[fk] = [c.split(".")[-1] for c in hit if c.split(".")[-1] in valid]
    for it in es.items:
        pred.setdefault(it["field_key"], [])
    return pred


if __name__ == "__main__":
    rows = []
    print("=== Table 2 主结果 + Table 3 消融 ===")
    for db, fn, sp in DBS:
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        pred = llm_pred(es, db, sp)
        lab = [1 if it["gold"] is not None else 0 for it in es.items]
        m = evaluate(es, pred, REPS)
        base = abstain_scores(es.items, pred, REPS, _spec, dims=())      # 仅匹配器弃权
        a0 = auroc([base[i["field_key"]] for i in es.items], lab)
        print("\n--- %s (n=%d, 正例 %d) ---" % (db, len(es), sum(lab)))
        print("  Direct-LLM: R@1=%.1f P=%.1f | 开放集 AUROC(仅自身弃权)=%.1f"
              % (m["Recall@1"], m["Precision"], 100 * a0))
        # 全部四维 + 逐维消融
        for tag, dims in ([("全部四维", DIMS)] +
                          [("− %s" % d, tuple(x for x in DIMS if x != d)) for d in DIMS] +
                          [("仅 %s" % d, (d,)) for d in DIMS]):
            s = abstain_scores(es.items, pred, REPS, _spec, dims=dims, w=W)
            sc = [s[i["field_key"]] for i in es.items]
            a = auroc(sc, lab)
            lo, hi = bootstrap_ci(sc, lab, n_boot=400)
            rows.append({"domain": db, "setting": tag, "dims": "+".join(dims),
                         "OpenSet_AUROC": round(100 * a, 2),
                         "CI_lo": round(100 * lo, 2), "CI_hi": round(100 * hi, 2),
                         "delta_vs_base": round(100 * (a - a0), 2),
                         "Recall@1": round(m["Recall@1"], 2),
                         "Precision": round(m["Precision"], 2),
                         "n_fields": len(es), "n_positive": sum(lab)})
            if tag in ("全部四维",) or tag.startswith("− "):
                print("    %-14s AUROC=%5.1f [%.1f, %.1f]  Δ=%+.1f"
                      % (tag, 100 * a, 100 * lo, 100 * hi, 100 * (a - a0)))
        rows.append({"domain": db, "setting": "仅匹配器自身弃权", "dims": "",
                     "OpenSet_AUROC": round(100 * a0, 2), "CI_lo": "", "CI_hi": "",
                     "delta_vs_base": 0.0, "Recall@1": round(m["Recall@1"], 2),
                     "Precision": round(m["Precision"], 2),
                     "n_fields": len(es), "n_positive": sum(lab)})
    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table3_abstain_ablation.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("\n-> results/tables/table3_abstain_ablation.csv")
