#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SchemaAlign-ICU / Step 02: 大表逐字段统计 —— 抗 OOM 两遍法

背景 (2026-08-18 事故记录):
  01_field_catalog.py 的 mimiciv/mimiciii stage 在 chartevents.csv (40 GB) 上做
  `GROUP BY itemid, valueuom` + 3 个 approx_quantile 时, 把 2 GiB 容器压到
  sshd 无法 fork, SSH 在 KEX 阶段被拒, 整台机器失联。
  根因: 每个分组要维护 3 个 t-digest 草图, 分组数 x 草图 的常驻内存超出预算。

本脚本的对策:
  Pass 1  只做常数内存聚合 (count / approx_count_distinct / min / max / avg / sum),
          不建任何草图 —— 得到全部字段的频次与单位。
  Pass 2  只对 Pass 1 选出的 top-K itemid 计算 p01/p50/p99, 分组数从数千降到 K。
  两遍都把 memory_limit 压到 500MB, 给 page cache 和 sshd 留出 1.5 GiB。

用法:
  python 02_bigtable_stats.py --table m4_chartevents --pass 1
  python 02_bigtable_stats.py --table m4_chartevents --pass 2 --topk 400
  python 02_bigtable_stats.py --table all --pass 1

输入 : data/ 下的大表 CSV
输出 : outputs/02_bigtable_stats/<table>_p1.csv , <table>_p2_quantiles.csv
"""
import argparse
import json
import os
import time

import duckdb

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
DATA = os.path.join(PROJ, "data")
OUT = os.path.join(PROJ, "outputs", "02_bigtable_stats")
TMP = os.path.join(PROJ, "cache", "duckdb_tmp")
M4 = os.path.join(DATA, "mimic-iv-3.1")
M3 = os.path.join(DATA, "mimic-iii-clinical-database-1.4")

os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

# table_key -> (事件表, 字典表, 事件id列, 单位列, 数值列, 分组主键列, 字典join列, 字典附加列)
SPEC = {
    "m4_chartevents": dict(
        ev=M4 + "/icu/chartevents.csv", di=M4 + "/icu/d_items.csv",
        idcol="itemid", uom="valueuom", num="valuenum", key="stay_id",
        dcols="any_value(d.label) AS label, any_value(d.abbreviation) AS abbreviation, "
              "any_value(d.category) AS category, any_value(d.unitname) AS dict_unit, "
              "any_value(d.param_type) AS param_type"),
    "m4_labevents": dict(
        ev=M4 + "/hosp/labevents.csv", di=M4 + "/hosp/d_labitems.csv",
        idcol="itemid", uom="valueuom", num="valuenum", key="hadm_id",
        dcols="any_value(d.label) AS label, any_value(d.fluid) AS fluid, "
              "any_value(d.category) AS category"),
    "m3_chartevents": dict(
        ev=M3 + "/CHARTEVENTS.csv", di=M3 + "/D_ITEMS.csv",
        idcol="ITEMID", uom="VALUEUOM", num="VALUENUM", key="ICUSTAY_ID",
        dcols="any_value(d.LABEL) AS label, any_value(d.ABBREVIATION) AS abbreviation, "
              "any_value(d.CATEGORY) AS category, any_value(d.UNITNAME) AS dict_unit, "
              "any_value(d.DBSOURCE) AS dbsource, any_value(d.PARAM_TYPE) AS param_type"),
    "m3_labevents": dict(
        ev=M3 + "/LABEVENTS.csv", di=M3 + "/D_LABITEMS.csv",
        idcol="ITEMID", uom="VALUEUOM", num="VALUENUM", key="HADM_ID",
        dcols="any_value(d.LABEL) AS label, any_value(d.FLUID) AS fluid, "
              "any_value(d.CATEGORY) AS category, any_value(d.LOINC_CODE) AS loinc_code"),
}


def con(mem="500MB"):
    c = duckdb.connect()
    c.execute("PRAGMA threads=1")
    c.execute("PRAGMA memory_limit='%s'" % mem)
    c.execute("PRAGMA temp_directory='%s'" % TMP)
    c.execute("PRAGMA preserve_insertion_order=false")
    return c


def R(p):
    return "read_csv('%s', header=true, all_varchar=true)" % p


def pass1(c, key):
    s = SPEC[key]
    dst = os.path.join(OUT, key + "_p1.csv")
    sql = """
      SELECT e.{id} AS itemid, e.{uom} AS observed_uom, {dcols},
             count(*) AS n_rows,
             approx_count_distinct(e.{key}) AS n_keys_approx,
             sum(CASE WHEN TRY_CAST(e.{num} AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
             round(min(TRY_CAST(e.{num} AS DOUBLE)),4)  AS v_min,
             round(avg(TRY_CAST(e.{num} AS DOUBLE)),4)  AS v_mean,
             round(max(TRY_CAST(e.{num} AS DOUBLE)),4)  AS v_max
      FROM {ev} e LEFT JOIN {di} d ON e.{id}=d.{id}
      GROUP BY e.{id}, e.{uom} ORDER BY n_rows DESC
    """.format(id=s["idcol"], uom=s["uom"], num=s["num"], key=s["key"],
               dcols=s["dcols"], ev=R(s["ev"]), di=R(s["di"]))
    t0 = time.time()
    c.execute("COPY (%s) TO '%s' (HEADER, DELIMITER ',')" % (sql, dst))
    print("[p1] %-16s %.1fs -> %s" % (key, time.time() - t0, dst), flush=True)
    return dst


def pass2(c, key, topk):
    """只对 Pass 1 里频次 top-K 的 itemid 算分位数, 把分组数压到 K。"""
    s = SPEC[key]
    p1 = os.path.join(OUT, key + "_p1.csv")
    if not os.path.exists(p1):
        raise SystemExit("先跑 --pass 1: %s 不存在" % p1)
    ids = c.execute(
        "SELECT DISTINCT itemid FROM read_csv('%s', header=true, all_varchar=true) "
        "ORDER BY TRY_CAST(n_rows AS BIGINT) DESC LIMIT %d" % (p1, topk)).fetchall()
    idlist = ",".join("'%s'" % r[0] for r in ids if r[0] is not None)
    dst = os.path.join(OUT, key + "_p2_quantiles.csv")
    sql = """
      SELECT e.{id} AS itemid, e.{uom} AS observed_uom,
             count(*) AS n_rows,
             round(approx_quantile(TRY_CAST(e.{num} AS DOUBLE),0.01),4) AS p01,
             round(approx_quantile(TRY_CAST(e.{num} AS DOUBLE),0.50),4) AS p50,
             round(approx_quantile(TRY_CAST(e.{num} AS DOUBLE),0.99),4) AS p99
      FROM {ev} e WHERE e.{id} IN ({ids})
      GROUP BY e.{id}, e.{uom} ORDER BY n_rows DESC
    """.format(id=s["idcol"], uom=s["uom"], num=s["num"], ev=R(s["ev"]), ids=idlist)
    t0 = time.time()
    c.execute("COPY (%s) TO '%s' (HEADER, DELIMITER ',')" % (sql, dst))
    print("[p2] %-16s topk=%d %.1fs -> %s" % (key, topk, time.time() - t0, dst), flush=True)
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="m4_chartevents")
    ap.add_argument("--pass", dest="phase", type=int, default=1)
    ap.add_argument("--topk", type=int, default=400)
    ap.add_argument("--mem", default="500MB")
    a = ap.parse_args()

    keys = list(SPEC) if a.table == "all" else a.table.split(",")
    c = con(a.mem)
    done = {}
    for k in keys:
        t0 = time.time()
        try:
            out = pass1(c, k) if a.phase == 1 else pass2(c, k, a.topk)
            done[k] = {"out": out, "seconds": round(time.time() - t0, 1)}
        except Exception as e:
            done[k] = {"error": str(e)[:300], "seconds": round(time.time() - t0, 1)}
            print("[ERR] %s %s" % (k, str(e)[:250]), flush=True)
    with open(os.path.join(OUT, "summary_pass%d.json" % a.phase), "w") as f:
        json.dump(done, f, indent=2, ensure_ascii=False)
    print("[done]", json.dumps(done, ensure_ascii=False)[:500], flush=True)
