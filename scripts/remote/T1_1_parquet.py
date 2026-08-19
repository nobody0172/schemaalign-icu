#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T1.1 · Parquet 化 —— 全项目 ROI 最高的一步 (执行文档 §5 T1.1)。

目标: 把 113 GB / 13.3 亿行的宽 CSV 压成统一 schema 的窄 Parquet,
      让后续每一次实验从「小时级」变成「分钟级」。

统一输出 schema (九张表全部对齐到这一套长表):
    stay_key   BIGINT   患者/住院键 (m4:stay_id|hadm_id, m3:ICUSTAY_ID|HADM_ID, eicu:patientunitstayid)
    field_key  VARCHAR  库内字段标识 —— **仅用于取数与 gold 构造, 绝不进入 FieldCard (C1)**
    t_offset   BIGINT   相对时间(分钟)。MIMIC 用 charttime 的 epoch 分钟, eICU 用原生 offset
    value_num  DOUBLE   数值 (TRY_CAST 失败为 NULL)
    value_uom  VARCHAR  实测单位, 无该列的表为 NULL
    src_table  VARCHAR  表来源 —— provenance 门控 V_prov 的输入

三种源 schema 形态各自处理:
  A 长表+显式 item   : chartevents / labevents / CHARTEVENTS / LABEVENTS / lab
  B 三级键值        : nurseCharting / respiratoryCharting  (cat|vallabel|valname 拼接)
  C 定宽表          : vitalPeriodic / vitalAperiodic       (UNPIVOT, 列名即字段名)

资源预算 (与 RewardProg-ICU 共存, 见 src/sa_guard.sh):
  threads=8/16, memory_limit=24GB/80GB, temp 落在项目自己的 cache/

断点续跑: 每张表完成后写 <name>.done; 重跑时自动跳过。--force 可强制重做。
C2: 全程不读 mimic-iv-note-2.2。
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
M4 = os.path.join(DATA, "mimic-iv-3.1")
M3 = os.path.join(DATA, "mimic-iii-clinical-database-1.4")
EI = os.path.join(DATA, "eicu_collaborative_research_database_2.0", "base")

os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)


def R(p):
    """全部按 VARCHAR 读入再显式转换 —— 避免类型推断在 4 亿行上翻车。"""
    return "read_csv('%s', header=true, all_varchar=true)" % p


# MIMIC 的 charttime 是绝对时间戳, 统一折算成 epoch 分钟, 与 eICU 的 offset 同量纲
def _epoch_min(col):
    return "CAST(epoch(TRY_CAST(%s AS TIMESTAMP)) / 60 AS BIGINT)" % col


JOBS = {
    # ---- 形态 A: 长表 + 显式 item ----
    "m4_chartevents": """
        SELECT TRY_CAST(stay_id AS BIGINT) AS stay_key, itemid AS field_key,
               {t} AS t_offset, TRY_CAST(valuenum AS DOUBLE) AS value_num,
               valueuom AS value_uom, 'mimiciv.icu.chartevents' AS src_table
        FROM {src}""".format(t=_epoch_min("charttime"), src=R(M4 + "/icu/chartevents.csv")),
    "m4_labevents": """
        SELECT TRY_CAST(hadm_id AS BIGINT) AS stay_key, itemid AS field_key,
               {t} AS t_offset, TRY_CAST(valuenum AS DOUBLE) AS value_num,
               valueuom AS value_uom, 'mimiciv.hosp.labevents' AS src_table
        FROM {src}""".format(t=_epoch_min("charttime"), src=R(M4 + "/hosp/labevents.csv")),
    "m3_chartevents": """
        SELECT TRY_CAST(ICUSTAY_ID AS BIGINT) AS stay_key, ITEMID AS field_key,
               {t} AS t_offset, TRY_CAST(VALUENUM AS DOUBLE) AS value_num,
               VALUEUOM AS value_uom, 'mimiciii.CHARTEVENTS' AS src_table
        FROM {src}""".format(t=_epoch_min("CHARTTIME"), src=R(M3 + "/CHARTEVENTS.csv")),
    "m3_labevents": """
        SELECT TRY_CAST(HADM_ID AS BIGINT) AS stay_key, ITEMID AS field_key,
               {t} AS t_offset, TRY_CAST(VALUENUM AS DOUBLE) AS value_num,
               VALUEUOM AS value_uom, 'mimiciii.LABEVENTS' AS src_table
        FROM {src}""".format(t=_epoch_min("CHARTTIME"), src=R(M3 + "/LABEVENTS.csv")),
    "eicu_lab": """
        SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key, labname AS field_key,
               TRY_CAST(labresultoffset AS BIGINT) AS t_offset,
               TRY_CAST(labresult AS DOUBLE) AS value_num,
               labmeasurenamesystem AS value_uom, 'eicu.lab' AS src_table
        FROM {src}""".format(src=R(EI + "/lab.csv")),
    # ---- 形态 B: 三级键值 (无单位列, 单位嵌在名字里) ----
    "eicu_nursecharting": """
        SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key,
               concat_ws('|', nursingchartcelltypecat, nursingchartcelltypevallabel,
                         nursingchartcelltypevalname) AS field_key,
               TRY_CAST(nursingchartoffset AS BIGINT) AS t_offset,
               TRY_CAST(nursingchartvalue AS DOUBLE) AS value_num,
               NULL AS value_uom, 'eicu.nurseCharting' AS src_table
        FROM {src}""".format(src=R(EI + "/nurseCharting.csv")),
    "eicu_respcharting": """
        SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key,
               concat_ws('|', respcharttypecat, respchartvaluelabel) AS field_key,
               TRY_CAST(respchartoffset AS BIGINT) AS t_offset,
               TRY_CAST(respchartvalue AS DOUBLE) AS value_num,
               NULL AS value_uom, 'eicu.respiratoryCharting' AS src_table
        FROM {src}""".format(src=R(EI + "/respiratoryCharting.csv")),
}

# ---- 形态 C: 定宽表 -> UNPIVOT, 列名即字段名 ----
_WIDE = {
    "eicu_vitalperiodic": (EI + "/vitalPeriodic.csv", "eicu.vitalPeriodic",
                           ["temperature", "sao2", "heartrate", "respiration", "cvp", "etco2",
                            "systemicsystolic", "systemicdiastolic", "systemicmean",
                            "pasystolic", "padiastolic", "pamean", "st1", "st2", "st3", "icp"]),
    "eicu_vitalaperiodic": (EI + "/vitalAperiodic.csv", "eicu.vitalAperiodic",
                            ["noninvasivesystolic", "noninvasivediastolic", "noninvasivemean",
                             "paop", "cardiacoutput", "cardiacinput", "svr", "svri", "pvr", "pvri"]),
}
for _name, (_path, _tbl, _cols) in _WIDE.items():
    _sel = " UNION ALL ".join(
        """SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key, '{c}' AS field_key,
                  TRY_CAST(observationoffset AS BIGINT) AS t_offset,
                  TRY_CAST("{c}" AS DOUBLE) AS value_num,
                  NULL AS value_uom, '{t}' AS src_table
           FROM {s} WHERE "{c}" IS NOT NULL AND "{c}" <> ''""".format(c=c, t=_tbl, s=R(_path))
        for c in _cols)
    JOBS[_name] = _sel


def connect(threads, mem):
    c = duckdb.connect()
    c.execute("PRAGMA threads=%d" % threads)
    c.execute("PRAGMA memory_limit='%s'" % mem)
    c.execute("PRAGMA temp_directory='%s'" % TMP)
    c.execute("PRAGMA preserve_insertion_order=false")
    return c


def run_one(con, name, sql, force):
    dst = os.path.join(OUT, name + ".parquet")
    done = dst + ".done"
    if os.path.exists(done) and not force:
        print("[skip] %s (已完成)" % name, flush=True)
        return json.load(open(done))
    t0 = time.time()
    con.execute("COPY (%s) TO '%s' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
                % (sql, dst))
    n = con.execute("SELECT count(*) FROM read_parquet('%s')" % dst).fetchone()[0]
    rec = {"rows": n, "bytes": os.path.getsize(dst), "seconds": round(time.time() - t0, 1)}
    json.dump(rec, open(done, "w"))
    print("[ok]   %-20s %13s 行  %6.2f GB  %7.1f s" %
          (name, format(n, ","), rec["bytes"] / 2**30, rec["seconds"]), flush=True)
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=int(os.environ.get("SA_DUCKDB_THREADS", 8)))
    ap.add_argument("--mem", default=os.environ.get("SA_DUCKDB_MEMLIMIT", "24GB"))
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    keys = a.only.split(",") if a.only else list(JOBS)
    print("[T1.1] %s  threads=%d mem=%s  待处理 %d 张表"
          % (time.strftime("%FT%TZ", time.gmtime()), a.threads, a.mem, len(keys)), flush=True)
    con = connect(a.threads, a.mem)
    summary, T0 = {}, time.time()
    for k in keys:
        try:
            summary[k] = run_one(con, k, JOBS[k], a.force)
        except Exception as e:
            summary[k] = {"error": str(e)[:400]}
            print("[ERR]  %-20s %s" % (k, str(e)[:250]), flush=True)
    ok = [v for v in summary.values() if "rows" in v]
    print("\n[T1.1] 完成 %d/%d, 总耗时 %.1f 分钟, 产物 %.2f GB, 总行数 %s"
          % (len(ok), len(keys), (time.time() - T0) / 60,
             sum(v["bytes"] for v in ok) / 2**30,
             format(sum(v["rows"] for v in ok), ",")), flush=True)
    json.dump(summary, open(os.path.join(OUT, "_summary_T1_1.json"), "w"),
              indent=2, ensure_ascii=False)
