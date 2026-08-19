#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用分层抽样估计参考集的整体错误率, 并按错误类型分解。

抽样是**分层且刻意偏向难例**的, 所以不能把 198 行里的错误率直接当作总体错误率,
必须按各层的总体规模加权。错误定义 = **两位独立专家一致地反对模型**（单人反对不计）。

输出: results/tables/table5_reference_error_rate.csv
"""
import csv, collections, json, os, sys, random
sys.path.insert(0, "src")
from schemaalign.gates.rules import FieldSpec, gate_all

GOLD, CAT = "data/gold", "data/field_catalog"
CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}

cat = {}
for db, fn in CATF.items():
    for r in csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")):
        cat[(db, r["field_key"])] = r
gold, ev = {}, {}
for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"), newline="", encoding="utf-8")):
    gold[(r["db"], r["field_key"])] = r["base_concept"]; ev[(r["db"], r["field_key"])] = r["evidence"]
unk = [(r["db"], r["field_key"], r["evidence"]) for r in csv.DictReader(
    open(os.path.join(GOLD, "unknown_set_adjudicated.csv"), newline="", encoding="utf-8"))]
reps = {}
for (db, k), c in gold.items():
    if db != "mimic-iv":
        continue
    row = cat.get((db, k), {}); n = int(row.get("n_rows") or 0)
    if c not in reps or n > reps[c][0]:
        reps[c] = (n, FieldSpec(db=db, field_key=k,
                                raw_name=(row.get("label") or k).split("|")[-1],
                                src_table=row.get("src_table", ""),
                                unit_observed=row.get("unit_observed") or None,
                                dtype_inferred="numeric", p01=row.get("p01"),
                                p50=row.get("p50"), p99=row.get("p99"),
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


NON = ("3-source agreement", "explicit table column", "structural")
POP = {}
POP["S1"] = len(sorted([(d, k) for d, k, _ in unk if (d, k) in cat],
                       key=lambda x: -cov(*x))[:600])
POP["S2"] = sum(1 for e in ev.values() if e.startswith("adjudicated:both_agree"))
POP["S3"] = (sum(1 for e in ev.values() if e.startswith("adjudicated:adjudicated"))
             + sum(1 for _, _, e in unk if e.startswith("adjudicated:adjudicated")))
s4 = 0
for (d, k), c in gold.items():
    if (d, k) in cat and c in reps:
        g = gate_all(spec(d, k), reps[c], concept_mode=True)
        if max(g.v_unit, g.v_type, g.v_specimen) >= 0.5:
            s4 += 1
POP["S4"] = s4
POP["S5"] = sum(1 for e in ev.values() if not e.startswith("adjudicated"))

dis = {int(r["item_no"]): r for r in csv.DictReader(
    open("results/tables/table5_expert_disagreements.csv", newline="", encoding="utf-8"))}
key = {int(r["item_no"]): r for r in csv.DictReader(
    open("human_validation/_sample_key_DO_NOT_SEND.csv", newline="", encoding="utf-8"))}

bys = collections.defaultdict(lambda: [0, 0])
for i, r in key.items():
    bys[r["stratum"]][0] += 1
    d = dis.get(i)
    if d and d["both_humans_agree_against_model"] == "True":
        bys[r["stratum"]][1] += 1

rows, num, den = [], 0.0, 0
print("%-4s %-30s %6s %6s %8s %8s" % ("层", "描述", "抽样n", "错误", "层错误率", "总体N"))
DESC = {"S1": "UNKNOWN judgements (high coverage)", "S2": "positives, LLM-only evidence",
        "S3": "arbitrated after disagreement", "S4": "positives where a check fires",
        "S5": "positives, non-LLM evidence"}
for st in ("S1", "S2", "S3", "S4", "S5"):
    n, e = bys[st]; N = POP[st]
    rate = e / n
    num += rate * N; den += N
    rows.append({"stratum": st, "description": DESC[st], "n_sampled": n, "n_errors": e,
                 "stratum_error_rate_%": round(100 * rate, 2), "population_N": N})
    print("%-4s %-30s %6d %6d %7.1f%% %8d" % (st, DESC[st], n, e, 100 * rate, N))
overall = num / den
# Wilson 区间, 用有效样本量近似
import math
z = 1.96; ntot = sum(v[0] for v in bys.values()); p = overall
lo = (p + z*z/(2*ntot) - z*math.sqrt(p*(1-p)/ntot + z*z/(4*ntot*ntot))) / (1 + z*z/ntot)
hi = (p + z*z/(2*ntot) + z*math.sqrt(p*(1-p)/ntot + z*z/(4*ntot*ntot))) / (1 + z*z/ntot)
print("\n分层加权的总体错误率 = %.2f%%  (95%% CI %.2f–%.2f%%), 覆盖总体 N=%d"
      % (100*overall, 100*lo, 100*hi, den))
rows.append({"stratum": "WEIGHTED TOTAL", "description": "stratified estimate",
             "n_sampled": ntot, "n_errors": sum(v[1] for v in bys.values()),
             "stratum_error_rate_%": round(100*overall, 2), "population_N": den,
             "CI_lo_%": round(100*lo, 2), "CI_hi_%": round(100*hi, 2)})

# 错误类型
cats = collections.Counter()
for i, d in dis.items():
    if d["both_humans_agree_against_model"] != "True":
        continue
    note = (d["clinician_note"] + " " + d["data_eng_note"]).lower()
    if "poc" in note or "fingerstick" in note or "床旁" in note or "末梢" in note or "指血" in note:
        cats["measurement method: point-of-care vs laboratory"] += 1
    elif "set rate" in note or "设定" in note:
        cats["measurement method: ventilator setting vs measured"] += 1
    elif "sao2" in note or "pulse oximetry" in note:
        cats["measurement method: arterial SaO2 vs pulse oximetry"] += 1
    elif d["model"] == "UNKNOWN":
        cats["model abstained, experts assigned"] += 1
    elif "cannot" in note or "拿不准" in note or "没有单位" in note:
        cats["insufficient metadata to decide"] += 1
    else:
        cats["concept naming granularity"] += 1
print("\n错误类型:")
for k, v in cats.most_common():
    print("   %-52s %d" % (k, v))
    rows.append({"stratum": "ERROR TYPE", "description": k, "n_errors": v})

os.makedirs("results/tables", exist_ok=True)
cols = ["stratum", "description", "n_sampled", "n_errors", "stratum_error_rate_%",
        "population_N", "CI_lo_%", "CI_hi_%"]
with open("results/tables/table5_reference_error_rate.csv", "w", newline="",
          encoding="utf-8") as f:
    w = csv.DictWriter(f, cols); w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
print("\n-> results/tables/table5_reference_error_rate.csv")
