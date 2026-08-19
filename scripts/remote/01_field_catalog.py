#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SchemaAlign-ICU / Step 01: 字段目录 (FieldCard 原料) 抽取  —— v2 低资源版

运行环境约束 (2026-08-18 实测):
  容器 cgroup memory.max = 2 GiB, cpu.max = 50000/100000 (0.5 vCPU), 无 GPU
  /root/autodl-tmp 可用 ~94 GB
因此 v2 相对 v1 的改动:
  1. memory_limit 降到 900MB, threads=2, 显式 temp_directory 落盘溢出
  2. 去掉 string_agg(DISTINCT ...) —— 改为把单位放进 GROUP BY key, 本地再聚合
  3. count(DISTINCT x) -> approx_count_distinct(x)  (HLL, 常数内存)
  4. 每条查询独立 try/except, 单条失败不影响后续

输入 : $DATA_ROOT 下 6 个数据集原始 CSV (只读)
输出 : $PROJ/outputs/01_field_catalog/<name>.csv  +  summary_<stage>.json

用法: python 01_field_catalog.py --stage {dict|cohort|mimiciv|mimiciii|eicu|aux|all}
"""
import argparse
import json
import os
import time
import traceback

import duckdb

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
DATA = os.path.join(PROJ, "data")
OUT = os.path.join(PROJ, "outputs", "01_field_catalog")
TMP = os.path.join(PROJ, "cache", "duckdb_tmp")
M4 = os.path.join(DATA, "mimic-iv-3.1")
M3 = os.path.join(DATA, "mimic-iii-clinical-database-1.4")
EICU = os.path.join(DATA, "eicu_collaborative_research_database_2.0", "base")
NOTE = os.path.join(DATA, "mimic-iv-note-2.2", "note")

os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
SUMMARY = {}


def con():
    c = duckdb.connect()
    c.execute("PRAGMA threads=2")
    c.execute("PRAGMA memory_limit='900MB'")
    c.execute("PRAGMA temp_directory='%s'" % TMP)
    c.execute("PRAGMA preserve_insertion_order=false")
    return c


def R(path):
    return "read_csv('%s', header=true, all_varchar=true)" % path


def run(c, name, sql, note=""):
    t0 = time.time()
    dst = os.path.join(OUT, name + ".csv")
    try:
        c.execute("COPY (%s) TO '%s' (HEADER, DELIMITER ',')" % (sql, dst))
        n = c.execute(
            "SELECT count(*) FROM read_csv('%s', header=true, all_varchar=true)" % dst
        ).fetchone()[0]
        dt = time.time() - t0
        SUMMARY[name] = {"rows": n, "seconds": round(dt, 1), "note": note}
        print("[ok ] %-34s rows=%-8d %7.1fs  %s" % (name, n, dt, note), flush=True)
    except Exception as e:
        SUMMARY[name] = {"error": str(e)[:400], "seconds": round(time.time() - t0, 1)}
        print("[ERR] %-34s %7.1fs  %s" % (name, time.time() - t0, str(e)[:250]), flush=True)
        traceback.print_exc()


# ------------------------------------------------------------------ 字典表
def stage_dict(c):
    run(c, "m4_d_items", "SELECT * FROM %s" % R(M4 + "/icu/d_items.csv"), "MIMIC-IV ICU item 字典")
    run(c, "m4_d_labitems", "SELECT * FROM %s" % R(M4 + "/hosp/d_labitems.csv"), "MIMIC-IV 化验字典")
    run(c, "m3_d_items", "SELECT * FROM %s" % R(M3 + "/D_ITEMS.csv"), "MIMIC-III item 字典")
    run(c, "m3_d_labitems", "SELECT * FROM %s" % R(M3 + "/D_LABITEMS.csv"), "MIMIC-III 化验字典 (含 LOINC)")
    run(c, "eicu_hospital", "SELECT * FROM %s" % R(EICU + "/hospital.csv"), "eICU 医院表")
    run(c, "m4_d_hcpcs", "SELECT * FROM %s LIMIT 5000" % R(M4 + "/hosp/d_hcpcs.csv"), "MIMIC-IV HCPCS 字典")

    # LOINC 桥接可行性: MIMIC-III / MIMIC-IV 化验 itemid 是否共享编号空间
    run(c, "bridge_loinc_m3_to_m4", """
        SELECT a.itemid, a.label AS m4_label, a.fluid AS m4_fluid, a.category AS m4_category,
               b.LABEL AS m3_label, b.FLUID AS m3_fluid, b.LOINC_CODE AS m3_loinc,
               CASE WHEN lower(trim(a.label))=lower(trim(b.LABEL)) THEN 1 ELSE 0 END AS label_exact_match
        FROM %s a INNER JOIN %s b ON TRY_CAST(a.itemid AS BIGINT)=TRY_CAST(b.ITEMID AS BIGINT)
        ORDER BY TRY_CAST(a.itemid AS BIGINT)""" % (R(M4 + "/hosp/d_labitems.csv"), R(M3 + "/D_LABITEMS.csv")),
        "MIMIC-III LOINC -> MIMIC-IV 化验字段的 itemid 桥接")


# ------------------------------------------------------------------ 队列
def stage_cohort(c):
    run(c, "coh_m4", """
        SELECT 'mimic-iv-3.1' AS db,
               (SELECT count(*) FROM %s) AS n_patients,
               (SELECT count(*) FROM %s) AS n_admissions,
               (SELECT count(*) FROM %s) AS n_icustays,
               (SELECT count(DISTINCT subject_id) FROM %s) AS n_icu_patients"""
        % (R(M4 + "/hosp/patients.csv"), R(M4 + "/hosp/admissions.csv"),
           R(M4 + "/icu/icustays.csv"), R(M4 + "/icu/icustays.csv")), "MIMIC-IV 队列规模")

    run(c, "coh_m4_los_mort", """
        SELECT count(*) AS n_stays,
               sum(CASE WHEN TRY_CAST(los AS DOUBLE)>=1.0 THEN 1 ELSE 0 END) AS n_los_ge_24h,
               sum(CASE WHEN TRY_CAST(los AS DOUBLE)>7.0 THEN 1 ELSE 0 END) AS n_los_gt_7d,
               round(avg(TRY_CAST(los AS DOUBLE)),3) AS mean_los_days,
               round(median(TRY_CAST(los AS DOUBLE)),3) AS median_los_days
        FROM %s""" % R(M4 + "/icu/icustays.csv"), "MIMIC-IV LOS 分布")

    run(c, "coh_m4_first_stay_labels", """
        WITH s AS (
          SELECT i.subject_id, i.hadm_id, i.stay_id, TRY_CAST(i.los AS DOUBLE) AS los,
                 row_number() OVER (PARTITION BY i.subject_id ORDER BY i.intime) AS rn
          FROM %s i)
        SELECT count(*) AS n_first_stays,
               sum(CASE WHEN los>=1.0 THEN 1 ELSE 0 END) AS n_ge_24h,
               sum(CASE WHEN los>=1.0 AND a.hospital_expire_flag='1' THEN 1 ELSE 0 END) AS n_ge24h_died,
               sum(CASE WHEN los>7.0 THEN 1 ELSE 0 END) AS n_los_gt_7d
        FROM s LEFT JOIN %s a ON s.hadm_id=a.hadm_id WHERE s.rn=1"""
        % (R(M4 + "/icu/icustays.csv"), R(M4 + "/hosp/admissions.csv")),
        "MIMIC-IV 首次 ICU stay + >=24h 后的两个主任务标签率")

    run(c, "coh_m3", """
        SELECT 'mimic-iii-1.4' AS db,
               (SELECT count(*) FROM %s) AS n_patients,
               (SELECT count(*) FROM %s) AS n_admissions,
               (SELECT count(*) FROM %s) AS n_icustays,
               (SELECT sum(CASE WHEN HOSPITAL_EXPIRE_FLAG='1' THEN 1 ELSE 0 END) FROM %s) AS n_died"""
        % (R(M3 + "/PATIENTS.csv"), R(M3 + "/ADMISSIONS.csv"),
           R(M3 + "/ICUSTAYS.csv"), R(M3 + "/ADMISSIONS.csv")), "MIMIC-III 队列规模")

    # CareVue / MetaVision 分层: 决定能否用 CareVue 子集规避与 MIMIC-IV 的患者重叠
    run(c, "coh_m3_dbsource", """
        SELECT DBSOURCE, count(*) AS n_icustays,
               count(DISTINCT SUBJECT_ID) AS n_patients,
               round(avg(TRY_CAST(LOS AS DOUBLE)),3) AS mean_los,
               sum(CASE WHEN TRY_CAST(LOS AS DOUBLE)>=1.0 THEN 1 ELSE 0 END) AS n_ge_24h,
               sum(CASE WHEN TRY_CAST(LOS AS DOUBLE)>7.0 THEN 1 ELSE 0 END) AS n_gt_7d
        FROM %s GROUP BY 1 ORDER BY n_icustays DESC""" % R(M3 + "/ICUSTAYS.csv"),
        "MIMIC-III ICUSTAYS 按 DBSOURCE (carevue/metavision) 分层")

    run(c, "coh_eicu", """
        SELECT count(*) AS n_unitstays, count(DISTINCT patienthealthsystemstayid) AS n_hospstays,
               count(DISTINCT uniquepid) AS n_patients, count(DISTINCT hospitalid) AS n_hospitals,
               sum(CASE WHEN lower(unitdischargestatus)='expired' THEN 1 ELSE 0 END) AS n_unit_expired,
               sum(CASE WHEN lower(hospitaldischargestatus)='expired' THEN 1 ELSE 0 END) AS n_hosp_expired,
               sum(CASE WHEN TRY_CAST(unitdischargeoffset AS DOUBLE)>=1440 THEN 1 ELSE 0 END) AS n_ge_24h,
               sum(CASE WHEN TRY_CAST(unitdischargeoffset AS DOUBLE)>10080 THEN 1 ELSE 0 END) AS n_gt_7d
        FROM %s""" % R(EICU + "/patient.csv"), "eICU 队列规模与标签率")

    run(c, "coh_eicu_by_hospital", """
        SELECT p.hospitalid, any_value(h.numbedscategory) AS numbeds, any_value(h.teachingstatus) AS teaching,
               any_value(h.region) AS region,
               count(*) AS n_unitstays, count(DISTINCT p.uniquepid) AS n_patients,
               sum(CASE WHEN lower(p.hospitaldischargestatus)='expired' THEN 1 ELSE 0 END) AS n_hosp_expired,
               sum(CASE WHEN TRY_CAST(p.unitdischargeoffset AS DOUBLE)>=1440 THEN 1 ELSE 0 END) AS n_ge_24h,
               count(DISTINCT p.unittype) AS n_unittypes
        FROM %s p LEFT JOIN %s h ON TRY_CAST(p.hospitalid AS BIGINT)=TRY_CAST(h.hospitalid AS BIGINT)
        GROUP BY 1 ORDER BY n_unitstays DESC""" % (R(EICU + "/patient.csv"), R(EICU + "/hospital.csv")),
        "eICU 逐医院规模 (医院级 held-out 依据)")

    run(c, "coh_eicu_unittype", "SELECT unittype, count(*) AS n FROM %s GROUP BY 1 ORDER BY n DESC"
        % R(EICU + "/patient.csv"), "eICU ICU 类型分布")


# ------------------------------------------------------------------ MIMIC-IV 观测字段
def stage_mimiciv(c):
    run(c, "m4_chartevents_items", """
        SELECT e.itemid, e.valueuom AS observed_uom,
               any_value(d.label) AS label, any_value(d.abbreviation) AS abbreviation,
               any_value(d.category) AS category, any_value(d.unitname) AS dict_unit,
               any_value(d.param_type) AS param_type,
               count(*) AS n_rows, approx_count_distinct(e.stay_id) AS n_stays_approx,
               sum(CASE WHEN TRY_CAST(e.valuenum AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.99),4) AS p99
        FROM %s e LEFT JOIN %s d ON e.itemid=d.itemid
        GROUP BY e.itemid, e.valueuom ORDER BY n_rows DESC"""
        % (R(M4 + "/icu/chartevents.csv"), R(M4 + "/icu/d_items.csv")),
        "MIMIC-IV chartevents: itemid x 实测单位 x 频次 x 分位数")

    run(c, "m4_labevents_items", """
        SELECT e.itemid, e.valueuom AS observed_uom,
               any_value(d.label) AS label, any_value(d.fluid) AS fluid, any_value(d.category) AS category,
               count(*) AS n_rows, approx_count_distinct(e.hadm_id) AS n_adm_approx,
               sum(CASE WHEN TRY_CAST(e.valuenum AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(e.valuenum AS DOUBLE),0.99),4) AS p99
        FROM %s e LEFT JOIN %s d ON e.itemid=d.itemid
        GROUP BY e.itemid, e.valueuom ORDER BY n_rows DESC"""
        % (R(M4 + "/hosp/labevents.csv"), R(M4 + "/hosp/d_labitems.csv")),
        "MIMIC-IV labevents: itemid x 实测单位 x 频次 x 分位数")

    run(c, "m4_inputevents_items", """
        SELECT e.itemid, e.amountuom AS observed_uom, e.rateuom AS observed_rateuom,
               any_value(d.label) AS label, any_value(d.category) AS category,
               count(*) AS n_rows, approx_count_distinct(e.stay_id) AS n_stays_approx,
               round(approx_quantile(TRY_CAST(e.amount AS DOUBLE),0.50),4) AS p50_amount
        FROM %s e LEFT JOIN %s d ON e.itemid=d.itemid
        GROUP BY 1,2,3 ORDER BY n_rows DESC"""
        % (R(M4 + "/icu/inputevents.csv"), R(M4 + "/icu/d_items.csv")),
        "MIMIC-IV inputevents: 实际给药 (provenance 对照组)")

    run(c, "m4_outputevents_items", """
        SELECT e.itemid, e.valueuom AS observed_uom, any_value(d.label) AS label,
               count(*) AS n_rows, approx_count_distinct(e.stay_id) AS n_stays_approx,
               round(approx_quantile(TRY_CAST(e.value AS DOUBLE),0.50),4) AS p50
        FROM %s e LEFT JOIN %s d ON e.itemid=d.itemid GROUP BY 1,2 ORDER BY n_rows DESC"""
        % (R(M4 + "/icu/outputevents.csv"), R(M4 + "/icu/d_items.csv")), "MIMIC-IV outputevents")

    run(c, "m4_procedureevents_items", """
        SELECT e.itemid, e.valueuom AS observed_uom, any_value(d.label) AS label,
               any_value(d.category) AS category,
               count(*) AS n_rows, approx_count_distinct(e.stay_id) AS n_stays_approx
        FROM %s e LEFT JOIN %s d ON e.itemid=d.itemid GROUP BY 1,2 ORDER BY n_rows DESC"""
        % (R(M4 + "/icu/procedureevents.csv"), R(M4 + "/icu/d_items.csv")), "MIMIC-IV procedureevents")

    run(c, "m4_prescriptions_drugs", """
        SELECT drug, dose_unit_rx, route, count(*) AS n_rows,
               approx_count_distinct(hadm_id) AS n_adm_approx
        FROM %s GROUP BY 1,2,3 ORDER BY n_rows DESC LIMIT 8000""" % R(M4 + "/hosp/prescriptions.csv"),
        "MIMIC-IV prescriptions 药名x剂量单位x途径 (处方, 非实际给药)")


# ------------------------------------------------------------------ MIMIC-III 观测字段
def stage_mimiciii(c):
    run(c, "m3_chartevents_items", """
        SELECT e.ITEMID AS itemid, e.VALUEUOM AS observed_uom,
               any_value(d.LABEL) AS label, any_value(d.ABBREVIATION) AS abbreviation,
               any_value(d.CATEGORY) AS category, any_value(d.UNITNAME) AS dict_unit,
               any_value(d.DBSOURCE) AS dbsource, any_value(d.PARAM_TYPE) AS param_type,
               count(*) AS n_rows, approx_count_distinct(e.ICUSTAY_ID) AS n_stays_approx,
               sum(CASE WHEN TRY_CAST(e.VALUENUM AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.99),4) AS p99
        FROM %s e LEFT JOIN %s d ON e.ITEMID=d.ITEMID
        GROUP BY 1,2 ORDER BY n_rows DESC"""
        % (R(M3 + "/CHARTEVENTS.csv"), R(M3 + "/D_ITEMS.csv")),
        "MIMIC-III CHARTEVENTS: ITEMID x 实测单位 (carevue/metavision 双体系)")

    run(c, "m3_labevents_items", """
        SELECT e.ITEMID AS itemid, e.VALUEUOM AS observed_uom,
               any_value(d.LABEL) AS label, any_value(d.FLUID) AS fluid,
               any_value(d.CATEGORY) AS category, any_value(d.LOINC_CODE) AS loinc_code,
               count(*) AS n_rows, approx_count_distinct(e.HADM_ID) AS n_adm_approx,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(e.VALUENUM AS DOUBLE),0.99),4) AS p99
        FROM %s e LEFT JOIN %s d ON e.ITEMID=d.ITEMID GROUP BY 1,2 ORDER BY n_rows DESC"""
        % (R(M3 + "/LABEVENTS.csv"), R(M3 + "/D_LABITEMS.csv")),
        "MIMIC-III LABEVENTS: ITEMID x 实测单位 (带 LOINC)")


# ------------------------------------------------------------------ eICU 观测字段
def stage_eicu(c):
    run(c, "eicu_lab_items", """
        SELECT labname, labmeasurenamesystem AS observed_uom, labtypeid,
               count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx,
               round(approx_quantile(TRY_CAST(labresult AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(labresult AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(labresult AS DOUBLE),0.99),4) AS p99
        FROM %s GROUP BY 1,2,3 ORDER BY n_rows DESC""" % R(EICU + "/lab.csv"),
        "eICU lab: labname x 单位 (唯一带显式单位列的 eICU 表)")

    run(c, "eicu_nursecharting_items", """
        SELECT nursingchartcelltypecat AS cat, nursingchartcelltypevallabel AS vallabel,
               nursingchartcelltypevalname AS valname,
               count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx,
               sum(CASE WHEN TRY_CAST(nursingchartvalue AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
               round(approx_quantile(TRY_CAST(nursingchartvalue AS DOUBLE),0.01),4) AS p01,
               round(approx_quantile(TRY_CAST(nursingchartvalue AS DOUBLE),0.50),4) AS p50,
               round(approx_quantile(TRY_CAST(nursingchartvalue AS DOUBLE),0.99),4) AS p99
        FROM %s GROUP BY 1,2,3 ORDER BY n_rows DESC""" % R(EICU + "/nurseCharting.csv"),
        "eICU nurseCharting: 三级字段名, 无单位列 -> 单位必须靠值域推断")

    run(c, "eicu_respcharting_items", """
        SELECT respchartvaluelabel, respcharttypecat, count(*) AS n_rows,
               approx_count_distinct(patientunitstayid) AS n_stays_approx,
               sum(CASE WHEN TRY_CAST(respchartvalue AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS n_nonnumeric,
               round(approx_quantile(TRY_CAST(respchartvalue AS DOUBLE),0.50),4) AS p50
        FROM %s GROUP BY 1,2 ORDER BY n_rows DESC""" % R(EICU + "/respiratoryCharting.csv"),
        "eICU respiratoryCharting 字段名")

    run(c, "eicu_infusiondrug", """
        SELECT drugname, count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx,
               round(approx_quantile(TRY_CAST(drugrate AS DOUBLE),0.50),4) AS p50_rate
        FROM %s GROUP BY 1 ORDER BY n_rows DESC""" % R(EICU + "/infusionDrug.csv"),
        "eICU infusionDrug: 单位内嵌在药名字符串中 (mcg/kg/min 等)")

    run(c, "eicu_medication", """
        SELECT drugname, dosage, routeadmin, count(*) AS n_rows,
               approx_count_distinct(patientunitstayid) AS n_stays_approx
        FROM %s GROUP BY 1,2,3 ORDER BY n_rows DESC LIMIT 8000""" % R(EICU + "/medication.csv"),
        "eICU medication 药名x剂量x途径")

    run(c, "eicu_intakeoutput", """
        SELECT celllabel, cellpath, count(*) AS n_rows,
               approx_count_distinct(patientunitstayid) AS n_stays_approx
        FROM %s GROUP BY 1,2 ORDER BY n_rows DESC LIMIT 8000""" % R(EICU + "/intakeOutput.csv"),
        "eICU intakeOutput 层级路径字段")

    run(c, "eicu_customlab", """
        SELECT labothername, count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx
        FROM %s GROUP BY 1 ORDER BY n_rows DESC LIMIT 3000""" % R(EICU + "/customLab.csv"),
        "eICU customLab: 站点自定义化验名 (开放集 UNKNOWN 的天然来源)")

    run(c, "eicu_physicalexam", """
        SELECT physicalexampath, count(*) AS n_rows,
               approx_count_distinct(patientunitstayid) AS n_stays_approx
        FROM %s GROUP BY 1 ORDER BY n_rows DESC LIMIT 8000""" % R(EICU + "/physicalExam.csv"),
        "eICU physicalExam 路径式字段")

    run(c, "eicu_vitalperiodic_scale", """
        SELECT count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx,
               sum(CASE WHEN heartrate IS NULL OR heartrate='' THEN 0 ELSE 1 END) AS nn_heartrate,
               sum(CASE WHEN sao2 IS NULL OR sao2='' THEN 0 ELSE 1 END) AS nn_sao2,
               sum(CASE WHEN respiration IS NULL OR respiration='' THEN 0 ELSE 1 END) AS nn_respiration,
               sum(CASE WHEN systemicsystolic IS NULL OR systemicsystolic='' THEN 0 ELSE 1 END) AS nn_sys_sbp,
               sum(CASE WHEN systemicmean IS NULL OR systemicmean='' THEN 0 ELSE 1 END) AS nn_sys_map,
               sum(CASE WHEN temperature IS NULL OR temperature='' THEN 0 ELSE 1 END) AS nn_temperature,
               sum(CASE WHEN cvp IS NULL OR cvp='' THEN 0 ELSE 1 END) AS nn_cvp,
               sum(CASE WHEN etco2 IS NULL OR etco2='' THEN 0 ELSE 1 END) AS nn_etco2
        FROM %s""" % R(EICU + "/vitalPeriodic.csv"),
        "eICU vitalPeriodic: 定宽表, 列名即字段 (无单位, 无 item 字典)")

    run(c, "eicu_vitalaperiodic_scale", """
        SELECT count(*) AS n_rows, approx_count_distinct(patientunitstayid) AS n_stays_approx,
               sum(CASE WHEN noninvasivesystolic IS NULL OR noninvasivesystolic='' THEN 0 ELSE 1 END) AS nn_nibp_sys,
               sum(CASE WHEN noninvasivemean IS NULL OR noninvasivemean='' THEN 0 ELSE 1 END) AS nn_nibp_map,
               sum(CASE WHEN paop IS NULL OR paop='' THEN 0 ELSE 1 END) AS nn_paop,
               sum(CASE WHEN cardiacoutput IS NULL OR cardiacoutput='' THEN 0 ELSE 1 END) AS nn_co
        FROM %s""" % R(EICU + "/vitalAperiodic.csv"),
        "eICU vitalAperiodic: 无创血压 (与 vitalPeriodic 有创构成多对一概念族)")


# ------------------------------------------------------------------ 辅助数据集
def stage_aux(c):
    run(c, "m4_note_scale", """
        SELECT 'discharge' AS kind, count(*) AS n_rows, approx_count_distinct(subject_id) AS n_subj FROM %s
        UNION ALL SELECT 'radiology', count(*), approx_count_distinct(subject_id) FROM %s"""
        % (R(NOTE + "/discharge.csv"), R(NOTE + "/radiology.csv")), "MIMIC-IV-Note 规模")

    run(c, "m4_note_detail_fields", """
        SELECT field_name, count(*) AS n_rows FROM %s GROUP BY 1 ORDER BY n_rows DESC LIMIT 300"""
        % R(NOTE + "/discharge_detail.csv"), "MIMIC-IV-Note discharge_detail field_name")


STAGES = {"dict": stage_dict, "cohort": stage_cohort, "mimiciv": stage_mimiciv,
          "mimiciii": stage_mimiciii, "eicu": stage_eicu, "aux": stage_aux}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dict")
    a = ap.parse_args()
    stages = list(STAGES) if a.stage == "all" else a.stage.split(",")
    c = con()
    t0 = time.time()
    for s in stages:
        print("\n===== STAGE %s =====" % s, flush=True)
        STAGES[s](c)
    sf = os.path.join(OUT, "summary_%s.json" % a.stage.replace(",", "_"))
    with open(sf, "w") as f:
        json.dump(SUMMARY, f, indent=2, ensure_ascii=False)
    print("\n[done] %.1fs -> %s" % (time.time() - t0, sf), flush=True)
