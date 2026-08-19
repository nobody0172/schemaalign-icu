#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T1.2 · 队列 / 分割 / 字段目录 (执行文档 §5 T1.2, Gate G1)。

**为什么必须重算**: 上一轮的字段目录在全量数据上统计, 违反 C4
「所有统计量只在 MIMIC-IV 训练分割上计算」。本脚本先定队列与分割, 再只在
train split 上算 MIMIC-IV 的统计; 目标域(CareVue/eICU)的统计来自其自身**无标签**数据。

产出 (outputs/T1_2/):
  cohort_{m4,m3cv,m3mv,eicu}.parquet   stay_key, split, label_mortality, label_los7
  field_catalog_{m4,m3cv,eicu}.csv     执行文档 §5 T1.2 表格要求的全部列
  unit_recovery_report.csv             单位可恢复率 (库 x 表 x 类别) —— 论文要报的新指标
  carevue_overlap_check.txt            G1 验收第 3 条
  _summary_T1_2.json

C1: field_key 仅用于取数, FieldCard 的构造在 T5, 届时不会带入任何主键。
C4: MIMIC-IV 的 p01/p50/p99/频率/缺失率一律只用 train split。
"""
import json
import os
import time

import duckdb

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
DATA = os.path.join(PROJ, "data")
PQ = os.path.join(PROJ, "data_parquet")
OUT = os.path.join(PROJ, "outputs", "T1_2")
TMP = os.path.join(PROJ, "cache", "duckdb_tmp")
M4, M3 = os.path.join(DATA, "mimic-iv-3.1"), os.path.join(DATA, "mimic-iii-clinical-database-1.4")
EI = os.path.join(DATA, "eicu_collaborative_research_database_2.0", "base")
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
S, T0 = {}, time.time()


def R(p):
    return "read_csv('%s', header=true, all_varchar=true)" % p


def step(con, name, sql, dst=None):
    t = time.time()
    if dst:
        con.execute("COPY (%s) TO '%s' %s" % (
            sql, dst, "(FORMAT PARQUET)" if dst.endswith(".parquet") else "(HEADER, DELIMITER ',')"))
        n = con.execute("SELECT count(*) FROM '%s'" % dst).fetchone()[0]
    else:
        n = con.execute(sql).fetchone()[0]
    S[name] = {"rows": n, "seconds": round(time.time() - t, 1)}
    print("[ok] %-30s %10s 行 %7.1fs" % (name, format(n, ","), S[name]["seconds"]), flush=True)


con = duckdb.connect()
con.execute("PRAGMA threads=%s" % os.environ.get("SA_DUCKDB_THREADS", "8"))
con.execute("PRAGMA memory_limit='%s'" % os.environ.get("SA_DUCKDB_MEMLIMIT", "24GB"))
con.execute("PRAGMA temp_directory='%s'" % TMP)
con.execute("PRAGMA preserve_insertion_order=false")

# ═══ 1. 队列与分割 ═══
print("\n=== 1. 队列与分割 (成人 / 首次 ICU stay / >=24h) ===", flush=True)

# MIMIC-IV: 患者级 70/10/20, 用 subject_id 的 hash 保证可复现且不跨分割泄漏
step(con, "cohort_m4", """
  WITH st AS (
    SELECT TRY_CAST(i.stay_id AS BIGINT) AS stay_key, TRY_CAST(i.subject_id AS BIGINT) AS pid,
           TRY_CAST(i.hadm_id AS BIGINT) AS hadm, TRY_CAST(i.los AS DOUBLE) AS los,
           TRY_CAST(i.intime AS TIMESTAMP) AS intime,
           row_number() OVER (PARTITION BY i.subject_id ORDER BY TRY_CAST(i.intime AS TIMESTAMP)) AS rk
    FROM {icu} i),
  ad AS (SELECT TRY_CAST(hadm_id AS BIGINT) AS hadm,
                TRY_CAST(hospital_expire_flag AS INT) AS died FROM {adm}),
  pt AS (SELECT TRY_CAST(subject_id AS BIGINT) AS pid,
                TRY_CAST(anchor_age AS INT) AS age FROM {pat})
  SELECT st.stay_key, st.hadm AS adm_key, st.pid,
         CASE WHEN hash(st.pid) % 10 < 7 THEN 'train'
              WHEN hash(st.pid) % 10 < 8 THEN 'val' ELSE 'test' END AS split,
         ad.died AS label_mortality, CASE WHEN st.los > 7 THEN 1 ELSE 0 END AS label_los7, st.los
  FROM st JOIN ad USING (hadm) JOIN pt USING (pid)
  WHERE st.rk = 1 AND st.los >= 1.0 AND pt.age >= 18
""".format(icu=R(M4 + "/icu/icustays.csv"), adm=R(M4 + "/hosp/admissions.csv"),
           pat=R(M4 + "/hosp/patients.csv")), os.path.join(OUT, "cohort_m4.parquet"))

# MIMIC-III: 按 DBSOURCE 分 carevue / metavision。年龄由 INTIME - DOB 求得(>89 已被偏移)
for tag, src in (("m3cv", "carevue"), ("m3mv", "metavision")):
    step(con, "cohort_" + tag, """
      WITH st AS (
        SELECT TRY_CAST(ICUSTAY_ID AS BIGINT) AS stay_key, TRY_CAST(SUBJECT_ID AS BIGINT) AS pid,
               TRY_CAST(HADM_ID AS BIGINT) AS hadm, TRY_CAST(LOS AS DOUBLE) AS los,
               TRY_CAST(INTIME AS TIMESTAMP) AS intime, lower(DBSOURCE) AS dbsrc,
               row_number() OVER (PARTITION BY SUBJECT_ID ORDER BY TRY_CAST(INTIME AS TIMESTAMP)) AS rk
        FROM {icu}),
      ad AS (SELECT TRY_CAST(HADM_ID AS BIGINT) AS hadm,
                    TRY_CAST(HOSPITAL_EXPIRE_FLAG AS INT) AS died FROM {adm}),
      pt AS (SELECT TRY_CAST(SUBJECT_ID AS BIGINT) AS pid,
                    TRY_CAST(DOB AS TIMESTAMP) AS dob FROM {pat})
      SELECT st.stay_key, st.hadm AS adm_key, st.pid, 'test' AS split, ad.died AS label_mortality,
             CASE WHEN st.los > 7 THEN 1 ELSE 0 END AS label_los7, st.los
      FROM st JOIN ad USING (hadm) JOIN pt USING (pid)
      WHERE st.rk = 1 AND st.los >= 1.0 AND st.dbsrc = '{d}'
        AND date_diff('year', pt.dob, st.intime) >= 18
    """.format(icu=R(M3 + "/ICUSTAYS.csv"), adm=R(M3 + "/ADMISSIONS.csv"),
               pat=R(M3 + "/PATIENTS.csv"), d=src), os.path.join(OUT, "cohort_%s.parquet" % tag))

# eICU: age 是字符串, '> 89' 需特判; unitdischargeoffset 单位为分钟
step(con, "cohort_eicu", """
  WITH p AS (
    SELECT TRY_CAST(patientunitstayid AS BIGINT) AS stay_key,
           TRY_CAST(uniquepid AS VARCHAR) AS pid, TRY_CAST(hospitalid AS BIGINT) AS hospid,
           CASE WHEN age = '> 89' THEN 90 ELSE TRY_CAST(age AS INT) END AS age_i,
           TRY_CAST(unitdischargeoffset AS BIGINT) AS unit_min,
           CASE WHEN hospitaldischargestatus = 'Expired' THEN 1 ELSE 0 END AS died,
           TRY_CAST(unitvisitnumber AS INT) AS visit
    FROM {pt})
  SELECT stay_key, stay_key AS adm_key, pid, hospid, 'test' AS split, died AS label_mortality,
         CASE WHEN unit_min > 10080 THEN 1 ELSE 0 END AS label_los7, unit_min/1440.0 AS los
  FROM p WHERE visit = 1 AND unit_min >= 1440 AND age_i >= 18
""".format(pt=R(EI + "/patient.csv")), os.path.join(OUT, "cohort_eicu.parquet"))

# ═══ 2. G1 验收第 3 条: CareVue 与 MIMIC-IV 无患者重叠 ═══
print("\n=== 2. CareVue / MIMIC-IV 重叠核查 ===", flush=True)
ov = con.execute("""
  SELECT (SELECT count(*) FROM {icu} WHERE lower(DBSOURCE)='carevue')                  AS cv_stays,
         (SELECT count(*) FROM {icu} WHERE lower(DBSOURCE)='metavision')               AS mv_stays,
         (SELECT count(*) FROM {icu} WHERE lower(DBSOURCE) NOT IN ('carevue','metavision')) AS both_stays,
         (SELECT count(*) FROM '{cv}')                                                  AS cv_cohort,
         (SELECT count(DISTINCT pid) FROM '{cv}')                                       AS cv_patients
""".format(icu=R(M3 + "/ICUSTAYS.csv"), cv=os.path.join(OUT, "cohort_m3cv.parquet"))).fetchone()
txt = [
    "CareVue / MIMIC-IV 患者重叠核查 (G1 验收第 3 条)",
    "=" * 62,
    "MIMIC-III ICUSTAYS 按 DBSOURCE:  carevue=%s  metavision=%s  其它=%s" % (ov[0], ov[1], ov[2]),
    "CareVue 队列 (成人/首次/>=24h): %s stays, %s 患者" % (ov[3], ov[4]),
    "",
    "结论: CareVue 子集全部满足 DBSOURCE='carevue', 与 metavision 子集无 stay 交集",
    "      (两者按 DBSOURCE 互斥切分; 'both' 类 %s 条已从两个队列中排除)。" % ov[2],
    "",
    "关于与 MIMIC-IV 的患者重叠 —— 无法直接核验, 如实记录:",
    "  MIMIC-III 与 MIMIC-IV 的 subject_id 已各自独立随机化, 不存在可对齐的患者标识,",
    "  因此'无重叠'只能由采集期推断: CareVue 采集期 2001-2008, MIMIC-IV 起于 2008。",
    "  MetaVision 期(2008-2012)与 MIMIC-IV 有时间交集 => 本项目只用 CareVue 作主外部域,",
    "  MetaVision 仅作 schema 难度对照, 并在论文中明确标注可能存在患者重叠。",
    "  【待验证 / 不可验证】此为设计约束, 非实测结论。",
]
open(os.path.join(OUT, "carevue_overlap_check.txt"), "w").write("\n".join(txt) + "\n")
print("\n".join(txt), flush=True)

# ═══ 3. 字段目录 (MIMIC-IV 只用 train split, 目标域用自身全量无标签数据) ═══
print("\n=== 3. 字段目录 ===", flush=True)

# 每张 parquet 声明它的 stay_key 语义: 'stay'=ICU stay 级, 'adm'=住院级(labevents)
# 字典表: 把 itemid -> label/abbreviation/category/dict_unit/param_type 补进目录。
# **这是 C1 的前提**: FieldCard 的 raw_name 只能用 label, 绝不能用 itemid。
DICTS = {
    # 第 8 槽 = specimen (标本类型)。指南 §7.4 的 CanonicalConcept 含该维,
    # 且第二轮仲裁中标注者据此判了 86 条 UNKNOWN (腹水/胸水/CSF 白蛋白 vs 血清白蛋白)。
    "m4_chartevents":  (M4 + "/icu/d_items.csv",     "itemid", "label", "abbreviation", "category", "unitname", "param_type", "NULL"),
    "m4_inputevents":  (M4 + "/icu/d_items.csv",     "itemid", "label", "abbreviation", "category", "unitname", "param_type", "NULL"),
    "m4_labevents":    (M4 + "/hosp/d_labitems.csv", "itemid", "label", "NULL",         "category", "NULL",     "NULL",       "fluid"),
    "m3_chartevents":  (M3 + "/D_ITEMS.csv",         "ITEMID", "LABEL", "ABBREVIATION", "CATEGORY", "UNITNAME", "PARAM_TYPE", "NULL"),
    "m3_inputevents_cv": (M3 + "/D_ITEMS.csv",       "ITEMID", "LABEL", "ABBREVIATION", "CATEGORY", "UNITNAME", "PARAM_TYPE", "NULL"),
    "m3_inputevents_mv": (M3 + "/D_ITEMS.csv",       "ITEMID", "LABEL", "ABBREVIATION", "CATEGORY", "UNITNAME", "PARAM_TYPE", "NULL"),
    "m3_labevents":    (M3 + "/D_LABITEMS.csv",      "ITEMID", "LABEL", "NULL",         "CATEGORY", "NULL",     "LOINC_CODE", "FLUID"),
}

KEYMAP = {
    "m4_chartevents": "stay", "m4_labevents": "adm",
    "m3_chartevents": "stay", "m3_labevents": "adm",
    "eicu_lab": "stay", "eicu_nursecharting": "stay", "eicu_respcharting": "stay",
    "eicu_vitalperiodic": "stay", "eicu_vitalaperiodic": "stay",
    # T1.1b 增补: 给药(实际) / 处方 —— 供 V_prov 门控与「去掉表来源」消融
    "m4_inputevents": "stay", "m3_inputevents_cv": "stay", "m3_inputevents_mv": "stay",
    "eicu_infusiondrug": "stay", "m4_prescriptions": "adm",
}

CAT = """
  WITH coh AS (SELECT DISTINCT {keycol} AS k FROM '{cohort}'
               WHERE {keycol} IS NOT NULL AND ({filt})),
  denom AS (SELECT count(DISTINCT {keycol}) AS n FROM '{cohort}' WHERE ({filt})),
  ev AS (SELECT e.* FROM read_parquet('{pq}') e SEMI JOIN coh ON e.stay_key = coh.k)
  SELECT field_key, src_table,
         count(*) AS n_rows,
         count(DISTINCT stay_key) AS n_keys,
         count(value_num) AS n_numeric,
         count(value_uom) AS n_with_uom,
         mode(value_uom) AS unit_observed,
         round(approx_quantile(value_num, 0.01), 4) AS p01,
         round(approx_quantile(value_num, 0.50), 4) AS p50,
         round(approx_quantile(value_num, 0.99), 4) AS p99,
         round(1.0*count(value_uom)/count(*), 4) AS unit_recovery_rate,
         round(1.0*count(value_num)/count(*), 4) AS numeric_rate,
         CASE WHEN 1.0*count(value_num)/count(*) >= 0.95 THEN 'numeric'
              WHEN 1.0*count(value_num)/count(*) <= 0.05 THEN 'categorical'
              ELSE 'mixed' END AS dtype_inferred,
         round(1.0*count(DISTINCT stay_key)/(SELECT n FROM denom), 4) AS coverage,
         round(1.0-1.0*count(DISTINCT stay_key)/(SELECT n FROM denom), 4) AS missing_rate,
         round(1.0*count(*)/count(DISTINCT stay_key), 3) AS obs_per_key
  FROM ev GROUP BY field_key, src_table
"""

# 带字典 join 的版本: label 等列来自字典表, 不是从 field_key 猜的
CAT_DICT = """
  WITH coh AS (SELECT DISTINCT {keycol} AS k FROM '{cohort}'
               WHERE {keycol} IS NOT NULL AND ({filt})),
  denom AS (SELECT count(DISTINCT {keycol}) AS n FROM '{cohort}' WHERE ({filt})),
  ev AS (SELECT e.* FROM read_parquet('{pq}') e SEMI JOIN coh ON e.stay_key = coh.k),
  ag AS (
    SELECT field_key, src_table, count(*) AS n_rows,
           count(DISTINCT stay_key) AS n_keys, count(value_num) AS n_numeric,
           count(value_uom) AS n_with_uom, mode(value_uom) AS unit_observed,
           round(approx_quantile(value_num,0.01),4) AS p01,
           round(approx_quantile(value_num,0.50),4) AS p50,
           round(approx_quantile(value_num,0.99),4) AS p99
    FROM ev GROUP BY field_key, src_table)
  SELECT ag.field_key, ag.src_table,
         d.{lab}  AS label,
         {abbr_expr} AS abbreviation,
         d.{cat}  AS dict_category,
         {unit_expr} AS dict_unit,
         {ptype_expr} AS param_type,
         {spec_expr} AS specimen,
         ag.n_rows, ag.n_keys, ag.n_numeric, ag.n_with_uom, ag.unit_observed,
         ag.p01, ag.p50, ag.p99,
         round(1.0*ag.n_with_uom/ag.n_rows,4) AS unit_recovery_rate,
         round(1.0*ag.n_numeric/ag.n_rows,4)  AS numeric_rate,
         CASE WHEN 1.0*ag.n_numeric/ag.n_rows >= 0.95 THEN 'numeric'
              WHEN 1.0*ag.n_numeric/ag.n_rows <= 0.05 THEN 'categorical'
              ELSE 'mixed' END AS dtype_inferred,
         round(1.0*ag.n_keys/(SELECT n FROM denom),4)     AS coverage,
         round(1.0-1.0*ag.n_keys/(SELECT n FROM denom),4) AS missing_rate,
         round(1.0*ag.n_rows/ag.n_keys,3)                 AS obs_per_key
  FROM ag LEFT JOIN {dict} d ON ag.field_key = d.{idc}
"""

DBS = {  # 库 -> (队列文件, 训练分割过滤, 该库的 parquet 前缀)
    "m4":   ("cohort_m4.parquet",   "split='train'", "m4_"),    # C4: 只用 train split
    "m3cv": ("cohort_m3cv.parquet", "1=1",           "m3_"),
    "eicu": ("cohort_eicu.parquet", "1=1",           "eicu_"),
}
for db, (cohort_f, filt, prefix) in DBS.items():
    tmp_names = []
    for name, keykind in KEYMAP.items():
        if not name.startswith(prefix):
            continue
        f = os.path.join(PQ, name + ".parquet")
        if not os.path.exists(f):
            print("[warn] 缺 %s" % f, flush=True)
            continue
        tname = "cat_" + name
        kc = "adm_key" if keykind == "adm" else "stay_key"
        if name in DICTS:
            dp, idc, lab, abbr, cat_, unit_, ptype_, spec_ = DICTS[name]
            sql = CAT_DICT.format(
                cohort=os.path.join(OUT, cohort_f), filt=filt, pq=f, keycol=kc,
                dict=R(dp), idc=idc, lab=lab, cat=cat_,
                abbr_expr=("NULL" if abbr == "NULL" else "d." + abbr),
                unit_expr=("NULL" if unit_ == "NULL" else "d." + unit_),
                ptype_expr=("NULL" if ptype_ == "NULL" else "d." + ptype_),
                spec_expr=("NULL" if spec_ == "NULL" else "d." + spec_))
        else:
            # eICU 与 prescriptions 的 field_key 本身就是名字, 无字典可 join
            sql = CAT.format(cohort=os.path.join(OUT, cohort_f), filt=filt, pq=f, keycol=kc)
            sql = sql.replace("SELECT field_key, src_table,",
                              "SELECT field_key, src_table, field_key AS label, "
                              "NULL AS abbreviation, NULL AS dict_category, "
                              "NULL AS dict_unit, NULL AS param_type, "
                              "NULL AS specimen,")
        con.execute("CREATE OR REPLACE TEMP TABLE %s AS %s" % (tname, sql))
        n = con.execute("SELECT count(*) FROM %s" % tname).fetchone()[0]
        print("     · %-22s %6s 字段" % (name, format(n, ",")), flush=True)
        tmp_names.append(tname)
    step(con, "field_catalog_" + db,
         "SELECT * FROM (%s) ORDER BY n_rows DESC"
         % " UNION ALL ".join("SELECT * FROM %s" % t for t in tmp_names),
         os.path.join(OUT, "field_catalog_%s.csv" % db))

# ═══ 4. 单位可恢复率报表 (论文要报的新指标) ═══
print("\n=== 4. 单位可恢复率 ===", flush=True)
step(con, "unit_recovery_report", """
  SELECT db, src_table,
         count(*)                                              AS n_fields,
         sum(CASE WHEN unit_observed IS NOT NULL THEN 1 ELSE 0 END) AS n_fields_with_unit,
         round(100.0*sum(CASE WHEN unit_observed IS NOT NULL THEN 1 ELSE 0 END)/count(*), 2) AS pct_fields_with_unit,
         sum(n_rows)                                           AS n_rows,
         sum(n_with_uom)                                       AS n_rows_with_unit,
         round(100.0*sum(n_with_uom)/sum(n_rows), 2)           AS pct_rows_with_unit
  FROM (
    SELECT 'MIMIC-IV'  AS db, * FROM read_csv('{a}', header=true) UNION ALL
    SELECT 'MIMIC-III-CareVue', * FROM read_csv('{b}', header=true) UNION ALL
    SELECT 'eICU',       * FROM read_csv('{c}', header=true))
  GROUP BY db, src_table ORDER BY db, n_rows DESC
""".format(a=os.path.join(OUT, "field_catalog_m4.csv"), b=os.path.join(OUT, "field_catalog_m3cv.csv"),
           c=os.path.join(OUT, "field_catalog_eicu.csv")),
     os.path.join(OUT, "unit_recovery_report.csv"))

S["_total_minutes"] = round((time.time() - T0) / 60, 2)
json.dump(S, open(os.path.join(OUT, "_summary_T1_2.json"), "w"), indent=2, ensure_ascii=False)
print("\n[T1.2] 完成, 总耗时 %.1f 分钟" % S["_total_minutes"], flush=True)
