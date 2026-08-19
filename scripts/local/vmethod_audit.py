#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V_method 的查全/查准分析。

盲测专家指出残余错误里 6/9 是测量方式混淆 (E47)。我们据此加了一维确定性谓词 V_method,
并按 C4 在 MIMIC-IV 验证分割上重标定 —— **验证集没有选中它**, 开放集 AUROC 一点没变。
本脚本回答"那它到底有没有用", 结论比"有用/没用"更有信息量。

输出: results/tables/table7_vmethod_audit.csv
"""
import csv, collections, os, sys
sys.path.insert(0, "src")
from schemaalign.gates.rules import v_method, measurement_method
exec(open("scripts/local/run_placement_matched.py").read().split('if __name__')[0])

rows, ex = [], []
tot = collections.Counter(); bym = collections.Counter()
for db, fn, sp in DBS:
    es = load_evalset(GOLD, CAT, db, fn, split=sp)
    f = o = 0
    for it in es.items:
        if it["gold"] is None:
            continue
        rep = REPS.get(it["gold"])
        if rep is None:
            continue
        v, why = v_method(_spec(it["row"], it["field_key"]), rep)
        if v >= 1.0:
            f += 1
            m = measurement_method((it["row"].get("label") or it["field_key"]))
            bym[m] += 1
            ex.append({"db": db, "field": (it["row"].get("label") or it["field_key"])[:48],
                       "concept": it["gold"], "method_detected": m, "reason": why[:90]})
        else:
            o += 1
    rows.append({"domain": db, "gold_positives": f + o, "flagged": f,
                 "flag_rate_%": round(100 * f / max(f + o, 1), 1)})
    print("%-10s 报警 %3d / %3d gold 正例 (%.1f%%)" % (db, f, f + o, 100 * f / max(f + o, 1)))

print("\n报警按检出的方式类型:")
for m, n in bym.most_common():
    print("   %-16s %d" % (m, n))
    rows.append({"domain": "ALL", "gold_positives": "", "flagged": n,
                 "flag_rate_%": "", "method_type": m})

os.makedirs("results/tables", exist_ok=True)
cols = ["domain", "gold_positives", "flagged", "flag_rate_%", "method_type"]
with open("results/tables/table7_vmethod_audit.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, cols); w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
with open("results/tables/table7_vmethod_flagged.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, list(ex[0].keys())); w.writeheader(); w.writerows(ex)
print("\n-> results/tables/table7_vmethod_audit.csv (+ _flagged.csv, %d 条)" % len(ex))
