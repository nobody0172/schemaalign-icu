#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Oracle 上限：单名标注者相对最终裁定 gold 的表现（人类天花板）。

比「gold 自己对自己 = 100%」有意义得多：
它刻画的是**在同一份协议下，一名独立标注者能达到的水平**，
即本任务的不可约误差。任何自动方法超过它都应被怀疑。
"""
import csv
import json
import os
import sys

sys.path.insert(0, "src")
from schemaalign.match.evalset import load_evalset
from schemaalign.match.metrics import evaluate

GOLD, CAT = "data/gold", "data/field_catalog"
DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
DBMAP = {"eicu": "eicu", "mimiciii": "mimic-iii", "mimiciv": "mimic-iv"}


def annotator_predictions():
    """从三轮仲裁结果里取**单名标注者**(source=both_agree 时即 A 的判定)。"""
    pred = {}
    for f in ("adjudication_result.json", "adjudication_result_drug.json",
              "adjudication_result_r2.json"):
        p = os.path.join(GOLD, f)
        if not os.path.exists(p):
            continue
        for a in json.load(open(p, encoding="utf-8"))["assignments"]:
            db = DBMAP[a["chunk"].rsplit("_", 1)[0]]
            pred[(db, a["field_key"])] = a["concept"]
    return pred


if __name__ == "__main__":
    ann = annotator_predictions()
    rows = []
    print("%-11s %6s %7s %7s %7s %7s" % ("域", "n", "R@1", "P", "F1", "Cov"))
    for db, fn, sp in DBS:
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        pr = {}
        for it in es.items:
            c = ann.get((db, it["field_key"]))
            pr[it["field_key"]] = [] if c in (None, "UNKNOWN", "UNSURE") else [c]
        m = evaluate(es, pr)
        m.update({"domain": db, "method": "Single annotator (human ceiling)"})
        rows.append(m)
        print("%-11s %6d %7.1f %7.1f %7.1f %7.1f"
              % (db, m["n_fields"], m["Recall@1"], m["Precision"], m["F1"], m["Coverage"]))
    cols = ["method", "domain", "Recall@1", "Precision", "Recall", "F1", "Coverage",
            "n_fields", "n_positive"]
    with open("results/tables/table2_oracle_ceiling.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("\n-> results/tables/table2_oracle_ceiling.csv")
