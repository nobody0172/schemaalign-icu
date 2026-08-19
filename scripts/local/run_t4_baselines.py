#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 · 跑 Exact / Ontology-only 两条基线, 产出 results/tables/table2_baselines.csv。"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, "src")

from schemaalign.gates.rules import FieldSpec
from schemaalign.match.baselines import (build_concept_loinc, embedding_baseline,
                                         exact_name_baseline, ontology_baseline)
from schemaalign.match.evalset import load_evalset
from schemaalign.match.metrics import evaluate

GOLD, CAT = "data/gold", "data/field_catalog"
# 开放集阈值 θ_open —— C4: 只能在 MIMIC-IV 验证分割上选, 此处先用固定占位值并如实标注
THETA = 0.55
DBS = [("mimic-iv", "field_catalog_m4.csv"), ("mimic-iii", "field_catalog_m3cv.csv"),
       ("eicu", "field_catalog_eicu.csv")]


def concept_representatives():
    """每个概念取 MIMIC-IV 侧行数最多的 gold 字段作代表 (C3: 只用源域)。"""
    lab = {}
    for fn in ("field_catalog_m4.csv",):
        for c in csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")):
            lab[c["field_key"]] = c.get("label") or c["field_key"]
    best = {}
    for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or not r["src_table"] or r["src_table"] == "table_column":
            continue
        n = int(r["n_rows"] or 0)
        c = r["base_concept"]
        if c not in best or n > best[c][0]:
            best[c] = (n, FieldSpec(db="mimic-iv", field_key=r["field_key"],
                                    raw_name=lab.get(r["field_key"], r["field_key"]).split("|")[-1],
                                    src_table=r["src_table"],
                                    unit_observed=r["unit_observed"] or None,
                                    dtype_inferred="numeric",
                                    p01=r["p01"], p50=r["p50"], p99=r["p99"]))
    return {c: v[1] for c, v in best.items()}


if __name__ == "__main__":
    reps = concept_representatives()
    concept_loinc, loinc_maps = build_concept_loinc(GOLD, "data/raw_catalog")
    print("概念代表 %d 个 | LOINC->概念 %d 条 | MIMIC-IV LOINC 回填 %d 项"
          % (len(reps), len(concept_loinc), len(loinc_maps["mimic-iv"])))

    rows = []
    for db, fn in DBS:
        es = load_evalset(GOLD, CAT, db, fn)
        print("\n[%s] %s" % (db, es.summary()))
        preds = [("Exact/normalized name", exact_name_baseline(es)),
                 ("Ontology only (LOINC)", ontology_baseline(es, loinc_maps, concept_loinc))]
        if os.path.isdir("data/embed"):
            for kind, tag, th in (("name", "Name embedding (frozen)", THETA),
                                  ("card", "FieldCard embedding, no gate", THETA)):
                try:
                    preds.append((tag, embedding_baseline(es, "data/embed", kind=kind, theta=th)))
                except Exception as e:
                    print("   [skip] %s: %s" % (tag, str(e)[:80]))
        for name, pred in preds:
            m = evaluate(es, pred, reps)
            m.update({"method": name, "domain": db})
            rows.append(m)
            print("  %-24s R@1=%5.1f  P=%5.1f R=%5.1f F1=%5.1f  Cov=%5.1f  "
                  "UnitViol=%s  OpenAUROC=%5.1f"
                  % (name, m["Recall@1"], m["Precision"], m["Recall"], m["F1"],
                     m["Coverage"], ("%.1f" % m["UnitViolRate"]) if m["UnitViolRate"] == m["UnitViolRate"] else "n/a",
                     m["OpenSet_AUROC"]))

    os.makedirs("results/tables", exist_ok=True)
    cols = ["method", "domain", "Recall@1", "Recall@5", "Recall@10", "Precision",
            "Recall", "F1", "Coverage", "UnitViolRate", "OpenSet_AUROC",
            "OpenSet_AUPRC", "n_fields", "n_positive", "n_unknown"]
    with open("results/tables/table2_baselines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("\n-> results/tables/table2_baselines.csv")
