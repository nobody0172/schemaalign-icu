#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T1.1 验收 —— 执行文档 §5 T1.1「验收」两条 + 数据完整性自查。

必须回答:
  ① 所有分片可被 duckdb 一次 read_parquet 打开?
  ② 总行数与 raw_catalog/00_file_inventory/files.tsv 的数据行数对得上?
  ③ **value_num 是否被 TRY_CAST 清空?** (Parquet 压到 1.5 B/行, 必须排除"全 NULL"的假象)
  ④ field_key / t_offset 是否有效?
"""
import json
import os

import duckdb

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
PQ = os.path.join(PROJ, "data_parquet")
INV = os.path.join(PROJ, "outputs", "00_file_inventory", "files.tsv")

# parquet 名 -> files.tsv 中的 (dataset, relpath)。定宽表 unpivot 后行数必然不等, 单列标注。
SRC = {
    "m4_chartevents": ("mimic-iv-3.1", "icu/chartevents.csv", 1),
    "m4_labevents": ("mimic-iv-3.1", "hosp/labevents.csv", 1),
    "m3_chartevents": ("mimic-iii-clinical-database-1.4", "CHARTEVENTS.csv", 1),
    "m3_labevents": ("mimic-iii-clinical-database-1.4", "LABEVENTS.csv", 1),
    "eicu_lab": ("eicu_collaborative_research_database_2.0", "base/lab.csv", 1),
    "eicu_nursecharting": ("eicu_collaborative_research_database_2.0", "base/nurseCharting.csv", 1),
    "eicu_respcharting": ("eicu_collaborative_research_database_2.0", "base/respiratoryCharting.csv", 1),
    "eicu_vitalperiodic": ("eicu_collaborative_research_database_2.0", "base/vitalPeriodic.csv", 0),
    "eicu_vitalaperiodic": ("eicu_collaborative_research_database_2.0", "base/vitalAperiodic.csv", 0),
}

inv = {}
for line in open(INV):
    ds, rel, b, r, c = line.rstrip("\n").split("\t")
    inv[(ds, rel)] = int(r)

con = duckdb.connect()
con.execute("PRAGMA threads=8"); con.execute("PRAGMA memory_limit='16GB'")

print("① 一次性打开全部分片")
glob = os.path.join(PQ, "*.parquet")
tot = con.execute("SELECT count(*) FROM read_parquet('%s')" % glob).fetchone()[0]
cols = con.execute("DESCRIBE SELECT * FROM read_parquet('%s') LIMIT 0" % glob).fetchall()
print("   ✓ 合并行数 %s ; schema = %s" % (format(tot, ","), [c[0] for c in cols]))

print("\n② 逐表行数核对 (vs files.tsv)")
print("   %-22s %14s %14s %s" % ("表", "parquet", "csv", "判定"))
bad = []
for name, (ds, rel, strict) in SRC.items():
    f = os.path.join(PQ, name + ".parquet")
    if not os.path.exists(f):
        print("   %-22s %14s %14s  ✗ 缺失" % (name, "-", "-")); bad.append(name); continue
    n = con.execute("SELECT count(*) FROM read_parquet('%s')" % f).fetchone()[0]
    m = inv[(ds, rel)]
    if strict:
        ok = (n == m)
        mark = "✓ 一致" if ok else "✗ 不一致 (差 %s)" % format(n - m, ",")
        if not ok:
            bad.append(name)
    else:
        mark = "· UNPIVOT 后为 %.2fx (源 %s 行 x 多列, 已滤空)" % (n / m, format(m, ","))
    print("   %-22s %14s %14s  %s" % (name, format(n, ","), format(m, ","), mark))

print("\n③ value_num 非空率 —— 排除 TRY_CAST 全部失败的假象")
print("   %-22s %13s %9s %12s %12s %12s" % ("表", "非空数值", "占比", "p01", "p50", "p99"))
for name in SRC:
    f = os.path.join(PQ, name + ".parquet")
    if not os.path.exists(f):
        continue
    r = con.execute("""
        SELECT count(*), count(value_num),
               round(approx_quantile(value_num,0.01),3),
               round(approx_quantile(value_num,0.50),3),
               round(approx_quantile(value_num,0.99),3)
        FROM read_parquet('%s')""" % f).fetchone()
    pct = 100.0 * r[1] / r[0] if r[0] else 0
    flag = "  ⚠ 疑似全空" if pct < 1 else ""
    print("   %-22s %13s %8.1f%% %12s %12s %12s%s"
          % (name, format(r[1], ","), pct, r[2], r[3], r[4], flag))

print("\n④ field_key / t_offset / stay_key 有效性")
print("   %-22s %10s %13s %13s %11s" % ("表", "字段数", "stay 数", "t_offset非空", "uom非空"))
for name in SRC:
    f = os.path.join(PQ, name + ".parquet")
    if not os.path.exists(f):
        continue
    r = con.execute("""
        SELECT approx_count_distinct(field_key), approx_count_distinct(stay_key),
               count(t_offset), count(value_uom)
        FROM read_parquet('%s')""" % f).fetchone()
    print("   %-22s %10s %13s %13s %11s"
          % (name, format(r[0], ","), format(r[1], ","), format(r[2], ","), format(r[3], ",")))

print("\n⑤ 抽样 5 行 (m4_chartevents)")
for row in con.execute("SELECT * FROM read_parquet('%s') WHERE value_num IS NOT NULL LIMIT 5"
                       % os.path.join(PQ, "m4_chartevents.parquet")).fetchall():
    print("   ", row)

print("\n=== 结论 ===")
print("   行数不一致的表:", bad if bad else "无")
sz = sum(os.path.getsize(os.path.join(PQ, f)) for f in os.listdir(PQ) if f.endswith(".parquet"))
print("   Parquet 总体积 %.2f GB (源 CSV 113.1 GB, 压缩 %.0fx)" % (sz / 2**30, 113.1 / (sz / 2**30)))
