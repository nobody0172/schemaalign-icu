#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把论文正文里出现的**每一个标量**连同它的来源文件写成一张表。

动机: zero-context 数字审计报告「某某数字在指定文件里找不到」——
不是因为数字是编的, 而是因为它散在不同产物里, 审计者不知道去哪找。
这张表让论文里任意一个数字都能一步回溯。

输出: results/tables/paper_constants.csv
"""
import csv, json, os, collections

R = []
def add(sym, val, src, note=""):
    R.append({"symbol": sym, "value": val, "source_file": src, "note": note})

# --- 参考集 ---
g = list(csv.DictReader(open("data/gold/gold_pairs.csv", newline="", encoding="utf-8")))
by = collections.defaultdict(set)
for r in g: by[r["base_concept"]].add(r["db"])
NON = ("3-source agreement", "explicit table column", "structural")
ev = collections.Counter("non-LLM" if any(r["evidence"].startswith(p) for p in NON)
                         else "LLM" for r in g)
evd = collections.Counter(r["evidence"].split(";")[0] for r in g)
add("gold pairs", len(g), "data/gold/gold_pairs.csv")
add("concepts covered", len(by), "data/gold/gold_pairs.csv")
add("concepts in all three DBs", sum(1 for c, s in by.items() if len(s) >= 3),
    "data/gold/gold_pairs.csv")
for db, n in collections.Counter(r["db"] for r in g).items():
    add("gold pairs, %s" % db, n, "data/gold/gold_pairs.csv")
add("non-LLM-evidence pairs", ev["non-LLM"], "data/gold/gold_pairs.csv (evidence column)")
add("non-LLM share (%)", round(100 * ev["non-LLM"] / len(g), 1), "data/gold/gold_pairs.csv")
add("  3-source agreement", evd["3-source agreement"], "data/gold/gold_pairs.csv")
add("  explicit table column", evd["explicit table column"], "data/gold/gold_pairs.csv")
add("  structural (shared lab itemid)",
    sum(v for k, v in evd.items() if k.startswith("structural")), "data/gold/gold_pairs.csv")
add("concept catalogue size",
    len(list(csv.DictReader(open("data/gold/concepts.csv", newline="", encoding="utf-8")))),
    "data/gold/concepts.csv")
add("adjudicated UNKNOWN fields",
    len(list(csv.DictReader(open("data/gold/unknown_set_adjudicated.csv",
                                 newline="", encoding="utf-8")))),
    "data/gold/unknown_set_adjudicated.csv")
a = json.load(open("data/gold/annotator_agreement.json"))
for k in ("n", "Po", "Pe", "kappa"):
    add("annotator agreement %s" % k, a[k], "data/gold/annotator_agreement.json")

# --- 动机层事实 ---
sa = list(csv.DictReader(open("data/gold/source_agreement.csv", newline="", encoding="utf-8")))
add("pairwise Jaccard min", min(float(r["jaccard"]) for r in sa), "data/gold/source_agreement.csv")
add("pairwise Jaccard max", max(float(r["jaccard"]) for r in sa), "data/gold/source_agreement.csv")
ur = list(csv.DictReader(open("data/field_catalog/unit_recovery_report.csv",
                              newline="", encoding="utf-8")))
z = [r for r in ur if r["db"] == "eICU" and r["n_fields_with_unit"] == "0"
     and r["src_table"] in ("eicu.vitalPeriodic", "eicu.nurseCharting",
                            "eicu.vitalAperiodic", "eicu.respiratoryCharting")]
add("eICU zero-unit tables: fields", sum(int(r["n_fields"]) for r in z),
    "data/field_catalog/unit_recovery_report.csv")
add("eICU zero-unit tables: rows", sum(int(r["n_rows"]) for r in z),
    "data/field_catalog/unit_recovery_report.csv")
add("eICU vitalPeriodic rows",
    next(int(r["n_rows"]) for r in ur if r["src_table"] == "eicu.vitalPeriodic"),
    "data/field_catalog/unit_recovery_report.csv", "quoted as 5.5e8 samples")

# --- 队列 ---
for db, fn in (("mimic-iv", "cohort_m4"), ("mimic-iii(CareVue)", "cohort_m3cv"),
               ("eicu", "cohort_eicu")):
    p = "data/field_catalog/%s.parquet" % fn
    if not os.path.exists(p):
        continue
    try:
        import duckdb
        n = duckdb.connect().execute("select count(*) from read_parquet(?)", [p]).fetchone()[0]
    except ImportError:
        import pyarrow.parquet as pq
        n = pq.ParquetFile(p).metadata.num_rows
    add("cohort stays, %s" % db, n, p)

# --- 结果表里的关键行 ---
for f, keys in (("table2_paired_delta.csv",
                 ("domain", "AUROC_base", "AUROC_ours", "delta", "paired_CI_lo",
                  "paired_CI_hi", "boot_p_delta_le_0")),
                ("table2_error_decomp.csv", ("domain", "over_share_of_errors_%")),
                ("table3_encoder_checks.csv", ("domain", "delta"))):
    p = os.path.join("results/tables", f)
    if not os.path.exists(p):
        continue
    for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
        add("%s[%s]" % (f.replace(".csv", ""), r["domain"]),
            " ".join("%s=%s" % (k, r[k]) for k in keys[1:]), "results/tables/" + f)

# --- 只有台账里有出处的常量, 明确标注 ---
for sym, val, note in (
        ("V_type false rejections traced to inferred type", "23 of 34",
         "EVIDENCE_LOG E30; derived during gate development, no standalone CSV"),
        ("cosine top1-top2 margin (median)", 0.068,
         "EVIDENCE_LOG E29; measured on MIMIC-IV val during lambda calibration"),
        ("precision collapse at unscaled penalty", "83.6 -> 51.5",
         "data/gold/lambda_calibration.json"),
        ("CareVue-MIMIC-IV chartevents itemid intersection", 0,
         "EVIDENCE_LOG E14"),
        ("full MIMIC-III-MIMIC-IV shared itemids", 2968, "EVIDENCE_LOG E14"),
        ("ricu concepts / databases", "119 / 5", "external: Bennett et al., GigaScience 2023"),
        ("MIMIC-IV d_items chartevents missing unit (%)", 85.3,
         "EVIDENCE_LOG session01; data/raw_catalog/01_field_catalog/")):
    add(sym, val, "(no standalone CSV)", note)

os.makedirs("results/tables", exist_ok=True)
with open("results/tables/paper_constants.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, ["symbol", "value", "source_file", "note"])
    w.writeheader(); w.writerows(R)
print("%d 个常量 -> results/tables/paper_constants.csv" % len(R))
for r in R[:6] + R[-7:]:
    print("  %-46s %-24s %s" % (r["symbol"], str(r["value"])[:24], r["source_file"]))
