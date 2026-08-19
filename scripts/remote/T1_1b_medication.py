#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T1.1b · 给药/处方表 Parquet 化 (T1.1 增补)。

**为什么加这四张表** —— 不是为了建模治疗动作 (idea §1 明确排除), 而是因为:
  1. 指南 §3.1 Table 1 难例 #12「MIMIC-IV prescriptions(处方) vs inputevents(实际给药)」
     是 V_prov 门控的核心检验对象;
  2. 执行文档 §5 T5 消融「− 表来源门控: 处方/给药、床旁/实验室是否被混配」
     必须同时拥有处方表与给药表才能做;
  3. 指南 §4 Q2 给 medication 组分配了 5 个概念 (升压药类)。
这些表只进入**字段目录与门控评测**, 不进入任何下游预测模型。

统一到与 T1.1 相同的 schema。给药表用 rate/rateuom (处方表无 rate, 用 dose_val_rx/dose_unit_rx)。
"""
import argparse
import json
import os
import time

import duckdb

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
DATA = os.path.join(PROJ, "data")
OUT = os.path.join(PROJ, "data_parquet")
TMP = os.path.join(PROJ, "cache", "duckdb_tmp")
M4, M3 = os.path.join(DATA, "mimic-iv-3.1"), os.path.join(DATA, "mimic-iii-clinical-database-1.4")
EI = os.path.join(DATA, "eicu_collaborative_research_database_2.0", "base")
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)


def R(p):
    return "read_csv('%s', header=true, all_varchar=true)" % p


def em(c):
    return "CAST(epoch(TRY_CAST(%s AS TIMESTAMP)) / 60 AS BIGINT)" % c


JOBS = {
    # 实际给药 (provenance = administration)
    "m4_inputevents": """
        SELECT TRY_CAST(stay_id AS BIGINT) AS stay_key, itemid AS field_key,
               {t} AS t_offset, TRY_CAST(rate AS DOUBLE) AS value_num,
               rateuom AS value_uom, 'mimiciv.icu.inputevents' AS src_table
        FROM {s}""".format(t=em("starttime"), s=R(M4 + "/icu/inputevents.csv")),
    "m3_inputevents_cv": """
        SELECT TRY_CAST(ICUSTAY_ID AS BIGINT) AS stay_key, ITEMID AS field_key,
               {t} AS t_offset, TRY_CAST(RATE AS DOUBLE) AS value_num,
               RATEUOM AS value_uom, 'mimiciii.INPUTEVENTS_CV' AS src_table
        FROM {s}""".format(t=em("CHARTTIME"), s=R(M3 + "/INPUTEVENTS_CV.csv")),
    "m3_inputevents_mv": """
        SELECT TRY_CAST(ICUSTAY_ID AS BIGINT) AS stay_key, ITEMID AS field_key,
               {t} AS t_offset, TRY_CAST(RATE AS DOUBLE) AS value_num,
               RATEUOM AS value_uom, 'mimiciii.INPUTEVENTS_MV' AS src_table
        FROM {s}""".format(t=em("STARTTIME"), s=R(M3 + "/INPUTEVENTS_MV.csv")),
    "eicu_infusiondrug": """
        SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key, drugname AS field_key,
               TRY_CAST(infusionoffset AS BIGINT) AS t_offset,
               TRY_CAST(drugrate AS DOUBLE) AS value_num,
               NULL AS value_uom, 'eicu.infusionDrug' AS src_table
        FROM {s}""".format(s=R(EI + "/infusionDrug.csv")),
    # 处方 (provenance = prescription) —— 与上面构成 V_prov 的硬拒对照
    "m4_prescriptions": """
        SELECT TRY_CAST(hadm_id AS BIGINT) AS stay_key, drug AS field_key,
               {t} AS t_offset, TRY_CAST(dose_val_rx AS DOUBLE) AS value_num,
               dose_unit_rx AS value_uom, 'mimiciv.hosp.prescriptions' AS src_table
        FROM {s}""".format(t=em("starttime"), s=R(M4 + "/hosp/prescriptions.csv")),
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=int(os.environ.get("SA_DUCKDB_THREADS", 8)))
    ap.add_argument("--mem", default=os.environ.get("SA_DUCKDB_MEMLIMIT", "24GB"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect()
    con.execute("PRAGMA threads=%d" % a.threads)
    con.execute("PRAGMA memory_limit='%s'" % a.mem)
    con.execute("PRAGMA temp_directory='%s'" % TMP)
    con.execute("PRAGMA preserve_insertion_order=false")
    S, T0 = {}, time.time()
    for k, sql in JOBS.items():
        dst = os.path.join(OUT, k + ".parquet"); done = dst + ".done"
        if os.path.exists(done) and not a.force:
            print("[skip] %s" % k, flush=True); continue
        t = time.time()
        try:
            con.execute("COPY (%s) TO '%s' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
                        % (sql, dst))
            n = con.execute("SELECT count(*) FROM read_parquet('%s')" % dst).fetchone()[0]
            S[k] = {"rows": n, "bytes": os.path.getsize(dst), "seconds": round(time.time() - t, 1)}
            json.dump(S[k], open(done, "w"))
            print("[ok]   %-20s %13s 行 %6.2f GB %7.1fs"
                  % (k, format(n, ","), S[k]["bytes"] / 2**30, S[k]["seconds"]), flush=True)
        except Exception as e:
            S[k] = {"error": str(e)[:300]}
            print("[ERR]  %-20s %s" % (k, str(e)[:200]), flush=True)
    print("\n[T1.1b] 完成, %.1f 分钟" % ((time.time() - T0) / 60), flush=True)
    json.dump(S, open(os.path.join(OUT, "_summary_T1_1b.json"), "w"), indent=2, ensure_ascii=False)
