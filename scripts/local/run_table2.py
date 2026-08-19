#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table 2 主表 —— 每个方法在 MIMIC-IV **验证分割** 上各自标定 θ_open (C4)。

为什么必须逐方法标定: 不同方法的打分尺度不同 (原始余弦 vs 门控加权分),
用同一个 θ 会系统性地误杀某些方法。实测: 把门控标定的 θ=0.90 套到 Name-embedding 上,
其 R@1 从 67.7 掉到 42.1 —— 那不是方法差, 是阈值错配。
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from schemaalign.gates.rules import FieldSpec
from schemaalign.match.baselines import (build_concept_loinc, embedding_baseline,
                                         exact_name_baseline, load_embeddings,
                                         ontology_baseline)
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import gated_predict
from schemaalign.match.metrics import evaluate

GOLD, CAT, EMB = "data/gold", "data/field_catalog", "data/embed"


def concept_representatives():
    lab = {c["field_key"]: (c.get("label") or c["field_key"])
           for c in csv.DictReader(open(os.path.join(CAT, "field_catalog_m4.csv"),
                                        newline="", encoding="utf-8"))}
    best = {}
    for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or r["src_table"] in ("", "table_column"):
            continue
        n = int(r["n_rows"] or 0)
        if r["base_concept"] not in best or n > best[r["base_concept"]][0]:
            best[r["base_concept"]] = (n, FieldSpec(
                db="mimic-iv", field_key=r["field_key"],
                raw_name=lab.get(r["field_key"], r["field_key"]).split("|")[-1],
                src_table=r["src_table"], unit_observed=r["unit_observed"] or None,
                dtype_inferred="numeric", p01=r["p01"], p50=r["p50"], p99=r["p99"]))
    return {c: v[1] for c, v in best.items()}


REPS = concept_representatives()
CL, LM = build_concept_loinc(GOLD, "data/raw_catalog")


def _emb_scores(es, kind):
    emb, cn, C = load_embeddings(EMB, es.db, kind)
    Cn = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    out = {}
    for it in es.items:
        v = emb.get(it["field_key"])
        if v is None:
            out[it["field_key"]] = []
            continue
        vn = v / (np.linalg.norm(v) + 1e-9)
        s = Cn @ vn
        idx = np.argsort(-s)[:10]
        out[it["field_key"]] = [(float(s[i]), cn[i]) for i in idx]
    return out


# 每个方法: (名字, 是否需要 θ, 打分函数 -> {field: [(score, concept)]} 或 直接 pred)
def scorers(es):
    return [
        ("Exact / normalized name", None, exact_name_baseline(es)),
        ("Ontology only (LOINC)", None, ontology_baseline(es, LM, CL)),
        ("Name embedding (frozen)", "score", _emb_scores(es, "name")),
        ("FieldCard embedding, no gate", "score", _emb_scores(es, "card")),
        ("Semantic recall + gate (T5a)", "score",
         gated_predict(es, EMB, REPS, theta=None, return_scores=True)[1]),
    ]


def apply_theta(raw, th):
    return {k: ([c for _, c in v] if v and v[0][0] >= th else []) for k, v in raw.items()}


if __name__ == "__main__":
    val = load_evalset(GOLD, CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
    thetas = {}
    for nm, kind, obj in scorers(val):
        if kind != "score":
            thetas[nm] = None
            continue
        grid = np.arange(-0.6, 1.001, 0.02)
        best = (None, -1)
        for th in grid:
            m = evaluate(val, apply_theta(obj, th), REPS)
            if m["F1"] > best[1]:
                best = (round(float(th), 3), m["F1"])
        thetas[nm] = best[0]
    print("θ_open 逐方法标定于 MIMIC-IV val (%d 字段, %d 正例) —— C4 合规"
          % (len(val), sum(1 for i in val.items if i["gold"])))
    for k, v in thetas.items():
        print("   %-34s θ = %s" % (k, v if v is not None else "n/a (精确匹配, 无需阈值)"))

    rows = []
    hdr = "%-32s %-10s %6s %6s %6s %6s %6s %6s %7s"
    print("\n" + hdr % ("方法", "域", "R@1", "R@10", "P", "F1", "Cov", "UnitV", "OpenAUC"))
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None),
                       ("eicu", "field_catalog_eicu.csv", None)):
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        for nm, kind, obj in scorers(es):
            pred = apply_theta(obj, thetas[nm]) if kind == "score" else obj
            m = evaluate(es, pred, REPS)
            m.update({"method": nm, "domain": db, "theta": thetas[nm]})
            rows.append(m)
            uv = "%.1f" % m["UnitViolRate"] if m["UnitViolRate"] == m["UnitViolRate"] else "n/a"
            print(hdr % (nm, db, "%.1f" % m["Recall@1"], "%.1f" % m["Recall@10"],
                         "%.1f" % m["Precision"], "%.1f" % m["F1"],
                         "%.1f" % m["Coverage"], uv, "%.1f" % m["OpenSet_AUROC"]))
        print()

    json.dump(thetas, open(os.path.join(GOLD, "theta_per_method.json"), "w"),
              indent=2, ensure_ascii=False)
    cols = ["method", "domain", "theta", "Recall@1", "Recall@5", "Recall@10", "Precision",
            "Recall", "F1", "Coverage", "UnitViolRate", "OpenSet_AUROC", "OpenSet_AUPRC",
            "n_fields", "n_positive", "n_unknown"]
    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table2_main.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("-> results/tables/table2_main.csv")
