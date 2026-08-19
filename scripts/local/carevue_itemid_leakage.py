#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计发现: 论文说「CareVue 的 chartevents itemid 与 MIMIC-IV 不相交」——**这是错的**。
m3cv 字段目录里有 661 个 220000+ 段(MetaVision 编号空间)的 chartevents itemid,
gold 里有 59 个与 MIMIC-IV 共享。stay 级筛选(DBSOURCE='carevue')没问题,
但 CareVue 期的 stay 仍有少量行使用 220000+ 编号。

本脚本量化这件事对结论的影响: 把 CareVue 评测**限制到真正 CareVue 期编号(itemid<20000)**
的 chartevents 字段, 重跑主结果。若结论不变, 说明共享编号没有在支撑结果。

输出: results/tables/table6_carevue_itemid_audit.csv
"""
import csv, json, os, sys
sys.path.insert(0, "src")
import numpy as np
exec(open("scripts/local/run_placement_matched.py").read().split('if __name__')[0])

cat = {r["field_key"]: r for r in csv.DictReader(
    open("data/field_catalog/field_catalog_m3cv.csv", newline="", encoding="utf-8"))}
m4keys = {r["field_key"] for r in csv.DictReader(
    open("data/field_catalog/field_catalog_m4.csv", newline="", encoding="utf-8"))}


def era(k):
    """真正的 CareVue 期编号: chartevents itemid < 20000; 化验/其它表不受影响。"""
    r = cat.get(k, {})
    if "CHARTEVENTS" not in (r.get("src_table") or "").upper():
        return True
    return (not k.isdigit()) or int(k) < 20000


rows = []
es = load_evalset(GOLD, CAT, "mimic-iii", "field_catalog_m3cv.csv")
pred = llm_pred(es, "mimic-iii", None)
for tag, keep in (("all CareVue fields", lambda it: True),
                  ("CareVue-era chartevents only", lambda it: era(it["field_key"])),
                  ("fields whose key also exists in MIMIC-IV",
                   lambda it: it["field_key"] in m4keys)):
    items = [it for it in es.items if keep(it)]
    if len(items) < 30:
        continue
    lab = [1 if i["gold"] is not None else 0 for i in items]
    sub = type(es)(es.db, es.concepts, items)
    b = abstain_scores(items, pred, REPS, _spec, dims=())
    o = abstain_scores(items, pred, REPS, _spec, dims=DIMSEL, w=W)
    sb = [b[i["field_key"]] for i in items]; so = [o[i["field_key"]] for i in items]
    a0, a1 = 100 * auroc(sb, lab), 100 * auroc(so, lab)
    lo, hi, p = paired_delta_ci(sb, so, lab)
    m = evaluate(sub, pred, REPS)
    rows.append({"subset": tag, "n_fields": len(items), "n_positive": sum(lab),
                 "Recall@1": round(m["Recall@1"], 2), "Precision": round(m["Precision"], 2),
                 "AUROC_base": round(a0, 2), "AUROC_ours": round(a1, 2),
                 "delta": round(a1 - a0, 2), "paired_CI_lo": round(100 * lo, 2),
                 "paired_CI_hi": round(100 * hi, 2), "boot_p": round(p, 4)})
    print("%-42s n=%3d pos=%3d  R@1=%5.1f  AUROC %5.2f->%5.2f  Δ=%+.2f CI[%+.2f,%+.2f] p=%.4f"
          % (tag, len(items), sum(lab), m["Recall@1"], a0, a1, a1 - a0,
             100 * lo, 100 * hi, p))

# 共享编号的规模
ch_shared = sum(1 for k, r in cat.items()
                if "CHARTEVENTS" in (r.get("src_table") or "").upper()
                and k.isdigit() and int(k) >= 220000)
print("\nm3cv 目录中 220000+ 段 chartevents 字段: %d / %d"
      % (ch_shared, sum(1 for r in cat.values()
                        if "CHARTEVENTS" in (r.get("src_table") or "").upper())))
with open("results/tables/table6_carevue_itemid_audit.csv", "w", newline="",
          encoding="utf-8") as f:
    w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("-> results/tables/table6_carevue_itemid_audit.csv")
