#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""污染对照: 按 gold_pairs.csv 的 evidence 列把正例分成「不依赖 LLM」与「LLM 仲裁」两个子集,
分别报 Direct-LLM 的 Recall@1。若存在同源污染, LLM 子集应当更高。

在**当前 gold 与当前评测分割**上重算 (E33 的旧数字来自更早的 gold 版本)。
输出: results/tables/table2_contamination.csv
"""
import csv, json, os, sys
sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import parse_mappings
from schemaalign.match.evalset import load_evalset

GOLD, CAT = "data/gold", "data/field_catalog"
DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
NONLLM = ("3-source agreement", "explicit table column", "structural")

ev = {}
for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"), newline="", encoding="utf-8")):
    ev[(r["db"], r["field_key"])] = r["evidence"]

def llm_pred(es, db, sp):
    raw = json.load(open("data/llm_baseline/direct_%s_%s.json" % (db, sp or "all")))
    valid = set(es.concepts); pred = {}
    for k, v in raw.items():
        if k == "_usage": continue
        mp = parse_mappings(v["text"])
        for fk, l, t in zip(v["keys"], v["labels"], v["tables"]):
            hit = mp.get("%s.%s" % (t, l)) or mp.get(l) or []
            pred[fk] = [c.split(".")[-1] for c in hit if c.split(".")[-1] in valid]
    for it in es.items: pred.setdefault(it["field_key"], [])
    return pred

rows = []
for db, fn, sp in DBS:
    es = load_evalset(GOLD, CAT, db, fn, split=sp)
    pred = llm_pred(es, db, sp)
    for tag, keep in (("non-LLM evidence", lambda e: any(e.startswith(p) for p in NONLLM)),
                      ("LLM-adjudicated", lambda e: e.startswith("adjudicated"))):
        sub = [it for it in es.items if it["gold"] is not None
               and keep(ev.get((db, it["field_key"]), ""))]
        if not sub: continue
        hit = sum(1 for it in sub if it["gold"] in pred.get(it["field_key"], [])[:1])
        rows.append({"domain": db, "gold_subset": tag, "n_positive": len(sub),
                     "Recall@1": round(100.0*hit/len(sub), 2)})
        print("[%-9s] %-18s n=%3d  R@1=%5.1f" % (db, tag, len(sub), 100.0*hit/len(sub)))

os.makedirs("results/tables", exist_ok=True)
with open("results/tables/table2_contamination.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("-> results/tables/table2_contamination.csv")
