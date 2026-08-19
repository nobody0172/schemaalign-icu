#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""编码器阶梯的匹配质量对比（支撑论文 C8：是否需要大模型语义表示）。

对每个编码器：字段侧用 name 模板，概念侧用概念名（同一文本空间，见台账 E19），
余弦排序 -> Recall@1/5/10。只比排序能力，不涉门控。
"""
import csv
import json
import os

import numpy as np

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
L = os.path.join(PROJ, "outputs", "T4_ladder")
W = os.path.join(PROJ, "work")
CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}


def rk(a):
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


if __name__ == "__main__":
    man = json.load(open(os.path.join(L, "_manifest.json")))
    concepts = [r["base_concept"] for r in csv.DictReader(
        open(os.path.join(W, "gold", "concepts.csv"), newline="", encoding="utf-8"))]
    cidx = {c: i for i, c in enumerate(concepts)}
    gold = {}
    for r in csv.DictReader(open(os.path.join(W, "gold", "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["base_concept"] in cidx:
            gold.setdefault(r["db"], {})[r["field_key"]] = cidx[r["base_concept"]]
    rows = []
    print("%-10s %-8s %6s %6s %6s %6s" % ("encoder", "db", "n", "R@1", "R@5", "R@10"))
    for name, meta in sorted(man["models"].items(), key=lambda x: x[1]["params_M"]):
        for db in CATF:
            f = os.path.join(L, "%s_%s_name.npy" % (name, db))
            kf = os.path.join(L, "%s_keys.csv" % db)
            cf = os.path.join(L, "%s_concept.npy" % name)
            if not (os.path.exists(f) and os.path.exists(cf)):
                continue
            E = rk(np.load(f).astype("float32"))
            C = rk(np.load(cf).astype("float32"))
            keys = [r["field_key"] for r in csv.DictReader(
                open(kf, newline="", encoding="utf-8"))]
            g = gold.get(db, {})
            sel = [(i, g[k]) for i, k in enumerate(keys) if k in g]
            if len(sel) < 10:
                continue
            idx = np.array([i for i, _ in sel]); y = np.array([t for _, t in sel])
            S = E[idx] @ C.T
            order = np.argsort(-S, axis=1)
            r1 = float((order[:, 0] == y).mean() * 100)
            r5 = float(np.mean([y[i] in order[i, :5] for i in range(len(y))]) * 100)
            r10 = float(np.mean([y[i] in order[i, :10] for i in range(len(y))]) * 100)
            print("%-10s %-8s %6d %6.1f %6.1f %6.1f" % (name, db, len(y), r1, r5, r10))
            rows.append({"encoder": name, "path": meta["path"], "params_M": meta["params_M"],
                         "pooling": meta["pooling"], "dim": meta["dim"], "domain": db,
                         "n_gold": len(y), "Recall@1": round(r1, 2),
                         "Recall@5": round(r5, 2), "Recall@10": round(r10, 2)})
    out = os.path.join(PROJ, "outputs", "table3_encoder_ladder.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("\n-> %s" % out)
