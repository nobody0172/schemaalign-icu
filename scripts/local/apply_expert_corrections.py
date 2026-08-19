#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两位专家**一致反对模型**的判定应用到参考集, 生成 data/gold_expert/ 下的修正版,
然后在修正版上重跑主结果, 看结论是否仍然成立。

只采纳「两位独立专家一致」的修正; 单人反对不动 —— 否则等于用一个人的意见覆盖仲裁结果。
原始参考集不改动, 修正版另存, 论文两个版本都报。
"""
import csv, os, shutil, sys

SRC, DST = "data/gold", "data/gold_expert"
os.makedirs(DST, exist_ok=True)
for f in os.listdir(SRC):
    p = os.path.join(SRC, f)
    if os.path.isfile(p):
        shutil.copy(p, os.path.join(DST, f))

key = {int(r["item_no"]): r for r in csv.DictReader(
    open("human_validation/_sample_key_DO_NOT_SEND.csv", newline="", encoding="utf-8"))}
dis = [r for r in csv.DictReader(
    open("results/tables/table5_expert_disagreements.csv", newline="", encoding="utf-8"))
    if r["both_humans_agree_against_model"] == "True"]

gp = list(csv.DictReader(open(os.path.join(SRC, "gold_pairs.csv"), newline="", encoding="utf-8")))
gcols = list(gp[0].keys())
uk = list(csv.DictReader(open(os.path.join(SRC, "unknown_set_adjudicated.csv"),
                              newline="", encoding="utf-8")))
ucols = list(uk[0].keys())
cat = {}
for db, fn in (("mimic-iv", "field_catalog_m4.csv"), ("mimic-iii", "field_catalog_m3cv.csv"),
               ("eicu", "field_catalog_eicu.csv")):
    for r in csv.DictReader(open(os.path.join("data/field_catalog", fn),
                                 newline="", encoding="utf-8")):
        cat[(db, r["field_key"])] = r

n_rm, n_add, n_relab, n_skip = 0, 0, 0, 0
for d in dis:
    db, fk, exp = d["db"], d["field_key"], d["clinician"]
    if exp == "UNSURE":
        n_skip += 1; continue
    if exp == "UNKNOWN":                       # 模型给了概念 -> 专家判 UNKNOWN
        before = len(gp)
        gp = [r for r in gp if not (r["db"] == db and r["field_key"] == fk)]
        if len(gp) < before:
            n_rm += 1
            c = cat.get((db, fk), {})
            uk.append({"db": db, "src_table": c.get("src_table", ""),
                       "label": c.get("label", ""), "field_key": fk,
                       "evidence": "expert:both_agree",
                       "reason": d["clinician_note"][:200]})
    elif d["model"] == "UNKNOWN":              # 模型判 UNKNOWN -> 专家给了概念
        uk = [r for r in uk if not (r["db"] == db and r["field_key"] == fk)]
        n_add += 1                              # 只移出 UNKNOWN 集, 不新增 gold 对(概念名需核对)
    else:                                       # 两边都给概念但不同
        hit = [r for r in gp if r["db"] == db and r["field_key"] == fk]
        if hit and exp in {x["base_concept"] for x in gp}:
            for r in hit:
                r["base_concept"] = exp
            n_relab += 1
        else:
            n_skip += 1

with open(os.path.join(DST, "gold_pairs.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, gcols); w.writeheader(); w.writerows(gp)
with open(os.path.join(DST, "unknown_set_adjudicated.csv"), "w", newline="",
          encoding="utf-8") as f:
    w = csv.DictWriter(f, ucols); w.writeheader()
    w.writerows([{c: r.get(c, "") for c in ucols} for r in uk])
print("专家修正: 撤销 gold 对 %d | 移出 UNKNOWN 集 %d | 改概念名 %d | 跳过(UNSURE/概念不在目录) %d"
      % (n_rm, n_add, n_relab, n_skip))
print("修正后 gold 对 %d, UNKNOWN %d -> %s" % (len(gp), len(uk), DST))
