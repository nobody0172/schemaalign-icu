#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构造给人类专家的盲测抽样工作表（外审要求的独立效度验证）。

抽样必须分层, 且**重点落在最可能出错的地方**, 而不是随机抽:
  S1 UNKNOWN·高覆盖      —— 77.1% 这个数字直接建立在这批判定上
  S2 正例·仅 LLM 证据    —— 最可能循环论证的一批
  S3 两标注者分歧·经仲裁 —— 本来就难
  S4 确定性检查报冲突    —— 单位/类型/标本冲突, 本文方法的作用点
  S5 正例·非 LLM 证据    —— 对照组, 应当接近全对; 用来检验专家自身的可靠性

盲测: 工作表**不含**模型给出的答案、不含 evidence 列、不含 itemid (C1)。
两类专家标注**同一批字段**, 因此可以同时得到
  (a) 人-人 Cohen's κ  —— 这是真正独立的一致性统计量
  (b) 人-模型一致率    —— 用于回答"参考集是否可信"

输出: human_validation/
  worksheet_clinician.csv / worksheet_data_engineer.csv  (同样的行, 分开两份避免互相看见)
  concept_catalogue.csv                                   (138 个概念 + 说明)
  _sample_key.csv                                         (内部答案表, 不要发给专家)
"""
import csv, json, os, random, sys
sys.path.insert(0, "src")
from schemaalign.gates.rules import FieldSpec, gate_all

GOLD, CAT, OUT = "data/gold", "data/field_catalog", "human_validation"
os.makedirs(OUT, exist_ok=True)
CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}
DBNAME = {"mimic-iv": "MIMIC-IV", "mimic-iii": "MIMIC-III (CareVue)", "eicu": "eICU-CRD"}
N = {"S1": 70, "S2": 50, "S3": 30, "S4": 30, "S5": 20}

cat = {}
for db, fn in CATF.items():
    for r in csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")):
        cat[(db, r["field_key"])] = r

gold, ev = {}, {}
for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"), newline="", encoding="utf-8")):
    gold[(r["db"], r["field_key"])] = r["base_concept"]
    ev[(r["db"], r["field_key"])] = r["evidence"]
unk = [(r["db"], r["field_key"], r["evidence"]) for r in
       csv.DictReader(open(os.path.join(GOLD, "unknown_set_adjudicated.csv"),
                           newline="", encoding="utf-8"))]
concepts = list(csv.DictReader(open(os.path.join(GOLD, "concepts.csv"),
                                    newline="", encoding="utf-8")))
reps = {}
for (db, k), c in gold.items():
    if db != "mimic-iv":
        continue
    row = cat.get((db, k), {})
    n = int(row.get("n_rows") or 0)
    if c not in reps or n > reps[c][0]:
        reps[c] = (n, FieldSpec(db=db, field_key=k,
                                raw_name=(row.get("label") or k).split("|")[-1],
                                src_table=row.get("src_table", ""),
                                unit_observed=row.get("unit_observed") or None,
                                dtype_inferred="numeric",
                                p01=row.get("p01"), p50=row.get("p50"), p99=row.get("p99"),
                                dtype_declared=bool((row.get("param_type") or "").strip()),
                                specimen=row.get("specimen") or None))
reps = {k: v[1] for k, v in reps.items()}


def spec(db, k):
    r = cat[(db, k)]
    return FieldSpec(db=db, field_key=k, raw_name=(r.get("label") or k).split("|")[-1],
                     src_table=r["src_table"], unit_observed=r["unit_observed"] or None,
                     dtype_inferred=r["dtype_inferred"], p01=r["p01"], p50=r["p50"],
                     p99=r["p99"], dtype_declared=bool((r.get("param_type") or "").strip()),
                     specimen=r.get("specimen") or None)


def cov(db, k):
    try:
        return float(cat[(db, k)].get("coverage") or 0)
    except ValueError:
        return 0.0


rng = random.Random(20260819)

# S1 UNKNOWN, 按覆盖率取前段再抽样
s1p = sorted([(d, k) for d, k, _ in unk if (d, k) in cat], key=lambda x: -cov(*x))[:600]
S1 = rng.sample(s1p, min(N["S1"], len(s1p)))
# S2 正例, 仅 LLM 证据
s2p = [(d, k) for (d, k), e in ev.items() if e.startswith("adjudicated:both_agree") and (d, k) in cat]
S2 = rng.sample(s2p, min(N["S2"], len(s2p)))
# S3 两标注者分歧 -> 仲裁
s3p = [(d, k) for (d, k), e in ev.items() if e.startswith("adjudicated:adjudicated") and (d, k) in cat]
s3p += [(d, k) for d, k, e in unk if e.startswith("adjudicated:adjudicated") and (d, k) in cat]
S3 = rng.sample(s3p, min(N["S3"], len(s3p)))
# S4 确定性检查报冲突的正例
s4p = []
for (d, k), c in gold.items():
    if (d, k) not in cat or c not in reps:
        continue
    g = gate_all(spec(d, k), reps[c], concept_mode=True)
    if max(g.v_unit, g.v_type, g.v_specimen) >= 0.5:
        s4p.append((d, k))
S4 = rng.sample(s4p, min(N["S4"], len(s4p)))
# S5 正例, 非 LLM 证据 (对照)
s5p = [(d, k) for (d, k), e in ev.items()
       if not e.startswith("adjudicated") and (d, k) in cat]
S5 = rng.sample(s5p, min(N["S5"], len(s5p)))

rows, seen = [], set()
for tag, sel in (("S1", S1), ("S2", S2), ("S3", S3), ("S4", S4), ("S5", S5)):
    for d, k in sel:
        if (d, k) in seen:
            continue
        seen.add((d, k))
        r = cat[(d, k)]
        rows.append({"stratum": tag, "db": d, "row": r, "key": (d, k)})
rng.shuffle(rows)   # 打乱, 专家看不出分层

WS = ["item_no", "database", "source_table", "field_name", "abbreviation",
      "dictionary_category", "declared_type", "specimen", "unit_recorded",
      "value_p01", "value_median", "value_p99", "pct_of_stays_with_this_field",
      "observations_per_stay",
      "YOUR_ANSWER_concept_or_UNKNOWN", "YOUR_CONFIDENCE_1to5", "YOUR_NOTE"]
out, key = [], []
for i, x in enumerate(rows, 1):
    r = x["row"]
    out.append({
        "item_no": i, "database": DBNAME[x["db"]],
        "source_table": r["src_table"].split(".", 1)[-1],
        "field_name": (r.get("label") or "").split("|")[-1] or r["field_key"],
        "abbreviation": r.get("abbreviation", ""),
        "dictionary_category": r.get("dict_category", ""),
        "declared_type": r.get("param_type", ""),
        "specimen": r.get("specimen", ""),
        "unit_recorded": r.get("unit_observed", ""),
        "value_p01": r.get("p01", ""), "value_median": r.get("p50", ""),
        "value_p99": r.get("p99", ""),
        "pct_of_stays_with_this_field": round(100 * cov(*x["key"]), 1),
        "observations_per_stay": r.get("obs_per_key", ""),
        "YOUR_ANSWER_concept_or_UNKNOWN": "", "YOUR_CONFIDENCE_1to5": "",
        "YOUR_NOTE": ""})
    key.append({"item_no": i, "stratum": x["stratum"], "db": x["db"],
                "field_key": r["field_key"],
                "model_answer": gold.get(x["key"], "UNKNOWN"),
                "model_evidence": ev.get(x["key"], "adjudicated:unknown")})

for who in ("clinician", "data_engineer"):
    with open(os.path.join(OUT, "worksheet_%s.csv" % who), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, WS); w.writeheader(); w.writerows(out)
with open(os.path.join(OUT, "_sample_key_DO_NOT_SEND.csv"), "w", newline="",
          encoding="utf-8") as f:
    w = csv.DictWriter(f, list(key[0].keys())); w.writeheader(); w.writerows(key)
with open(os.path.join(OUT, "concept_catalogue.csv"), "w", newline="",
          encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, ["concept_name", "group", "units_seen_in_data"])
    w.writeheader()
    for c in sorted(concepts, key=lambda x: (x["group"], x["base_concept"])):
        w.writerow({"concept_name": c["base_concept"], "group": c["group"],
                    "units_seen_in_data": c["units_observed"]})

import collections
print("抽样 %d 个字段" % len(out))
print("分层:", dict(collections.Counter(k["stratum"] for k in key)))
print("按库:", dict(collections.Counter(k["db"] for k in key)))
print("模型判 UNKNOWN 的比例: %.1f%%"
      % (100.0 * sum(1 for k in key if k["model_answer"] == "UNKNOWN") / len(key)))
print("-> %s" % OUT)
