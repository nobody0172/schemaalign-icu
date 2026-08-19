# -*- coding: utf-8 -*-
"""T2 · 概念目录 / UNKNOWN 集 / 仲裁清单 (Gate G2 的四项交付)。

配额 (指南 §4 Q2 裁决): vital 20 / lab 35 / respiratory-and-bloodgas 12 /
                        demographic 8 / medication 5  = 80 概念

人口学与药物两组不来自 itemid, 单独处理:
  - demographic: 直接取自 patient/admission 表的列, 三库均为显式列, 无歧义
  - medication : 升压药类, 来自 MIMIC-IV inputevents / MIMIC-III INPUTEVENTS_* / eICU infusionDrug

UNKNOWN 集 (执行文档 §5 T2「无需人工构造」):
  eICU customLab 站点自定义化验名 + infusionDrug 药名中不在概念目录内者
  + MIMIC-IV d_items 的 Skin-Impairment / Access Lines 类别字段
"""
import collections
import csv
import os

__all__ = ["DEMOGRAPHIC", "MEDICATION", "build_catalog"]

# ── 人口学: 三库都是表内显式列, 映射无歧义, 直接写死并注明出处 ──────────
DEMOGRAPHIC = [
    # (base_concept, mimic-iv, mimic-iii, eicu)
    ("age",             "hosp/patients.anchor_age",      "PATIENTS.DOB+ICUSTAYS.INTIME", "patient.age"),
    ("sex",             "hosp/patients.gender",          "PATIENTS.GENDER",              "patient.gender"),
    ("admission_weight", "icu/chartevents:Admission Weight", "CHARTEVENTS:Admit Wt",     "patient.admissionweight"),
    ("admission_height", "icu/chartevents:Height",        "CHARTEVENTS:Height",          "patient.admissionheight"),
    ("ethnicity",       "hosp/admissions.race",          "ADMISSIONS.ETHNICITY",         "patient.ethnicity"),
    ("admission_type",  "hosp/admissions.admission_type", "ADMISSIONS.ADMISSION_TYPE",   "patient.unitadmitsource"),
    ("first_careunit",  "icu/icustays.first_careunit",   "ICUSTAYS.FIRST_CAREUNIT",      "patient.unittype"),
    ("hospital_los",    "hosp/admissions(dis-adm)",      "ADMISSIONS(DIS-ADM)",          "patient.hospitaldischargeoffset"),
]

# ── 药物: 只留升压药类 5 个 (指南 §4 Q2: CareVue 侧给药表结构与 MIMIC-IV 不可比) ──
MEDICATION = ["norepinephrine", "epinephrine", "dopamine", "dobutamine", "vasopressin"]

GROUPS = {"vital": 20, "lab": 35, "respiratory_bloodgas": 12,
          "demographic": 8, "medication": 5}

# 概念 -> 组 (人工指派, 依据临床类别而非字符串)
GROUP_OF = {}
for _c in ("heart_rate", "respiratory_rate", "temperature", "spo2", "sbp", "dbp", "mbp",
           "bp", "cvp", "icp", "etco2", "gcs_total", "gcs_eyes", "gcs_motor", "gcs_verbal",
           "urine_output", "weight", "height", "co", "ci", "sv", "svr", "svri", "paop",
           "pasystolic", "padiastolic", "pamean", "cpp", "iap", "pain_score",
           "sedation_score", "delirium_score", "temperaturelocation"):
    GROUP_OF[_c] = "vital"
for _c in ("albumin", "anion_gap", "bands", "bicarbonate", "bilirubin_total", "bilirubin_direct",
           "bilirubin_indirect", "bun", "calcium", "chloride", "creatinine", "glucose",
           "hematocrit", "hemoglobin", "inr", "lactate", "platelets", "potassium", "sodium",
           "wbc", "pt", "ptt", "alt", "ast", "alkaline_phosphatase", "ggt", "globulin",
           "total_protein", "amylase", "ck_cpk", "ck_mb", "troponin_t", "crp", "d_dimer",
           "fibrinogen", "ld_ldh", "ntprobnp", "thrombin", "mch", "mchc", "mcv", "rbc",
           "rdw", "rdwsd", "nrbc", "neutrophils", "lymphocytes", "monocytes", "eosinophils",
           "basophils", "neutrophils_abs", "lymphocytes_abs", "monocytes_abs",
           "eosinophils_abs", "basophils_abs", "granulocytes_abs", "immature_granulocytes",
           "metamyelocytes", "atypical_lymphocytes", "magnesium", "phosphate"):
    GROUP_OF[_c] = "lab"
for _c in ("ph", "po2", "pco2", "so2", "base_excess", "base_deficit", "hco3", "aado2",
           "carboxyhemoglobin", "methemoglobin", "fio2", "peep", "o2_flow", "o2flow",
           "o2_device", "tidal_volume", "tidalvolume", "minute_volume", "plateau_pressure",
           "ventilator_mode", "ventilationrate", "respiratory_rate_set",
           "respiratory_rate_total", "respiratory_rate_spontaneous", "requiredo2",
           "intubated", "selfextubated", "svo2"):
    GROUP_OF[_c] = "respiratory_bloodgas"
for _c in MEDICATION + ["rate_norepinephrine", "rate_epinephrine", "rate_dopamine",
                        "rate_dobutamine"]:
    GROUP_OF[_c] = "medication"
for _c in ("delirium_scale", "delirium_score", "sedation_scale", "sedation_goal",
           "pain_goal", "ectopy_type", "ectopy_frequency", "ectopy_type_secondary",
           "ectopy_frequency_secondary", "temperature_site", "pvr", "pvri"):
    GROUP_OF[_c] = "vital"
for _c in ("gcs_unable", "ventilator", "ventilator_type", "ventilator_mode_hamilton",
           "o2_flow_additional"):
    GROUP_OF[_c] = "respiratory_bloodgas"
for _c, _, _, _ in DEMOGRAPHIC:
    GROUP_OF[_c] = "demographic"


def build_catalog(gold_dir, raw_catalog_dir, catalog_dir):
    F = lambda n: os.path.join(gold_dir, n)

    # ── 概念目录 ────────────────────────────────────────────────────
    cov, evid = collections.defaultdict(set), collections.defaultdict(list)
    for fn, status in (("gold_pairs_auto.csv", "auto"),
                       ("adjudication_queue.csv", "needs_adjudication")):
        p = F(fn)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
            cov[r["base_concept"]].add(r["db"])
            evid[r["base_concept"]].append((status, r["db"], r["unit_observed"],
                                            r["p50"], r["n_rows"]))
    for c, *_ in [(d[0],) for d in DEMOGRAPHIC]:
        cov[c] = {"mimic-iv", "mimic-iii", "eicu"}

    rows = []
    for c in sorted(cov):
        dbs = cov[c]
        g = GROUP_OF.get(c, "unassigned")
        st = "auto" if len(dbs) == 3 else "needs_adjudication"
        if g == "demographic":
            st = "auto_table_column"
        units = sorted({e[2] for e in evid[c] if e[2]})
        rows.append({
            "base_concept": c, "group": g, "status": st,
            "n_dbs_covered": len(dbs), "dbs_covered": "+".join(sorted(dbs)),
            "dbs_missing": "+".join(sorted({"mimic-iv", "mimic-iii", "eicu"} - dbs)),
            "units_observed": ";".join(units[:4]),
            "n_source_pairs": len(evid[c]),
        })
    with open(F("concepts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    # ── 人口学映射表 ─────────────────────────────────────────────────
    with open(F("gold_pairs_demographic.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["base_concept", "group", "mimic-iv", "mimic-iii", "eicu", "note"])
        for c, a, b, d in DEMOGRAPHIC:
            w.writerow([c, "demographic", a, b, d, "表内显式列, 三库映射无歧义"])

    # ── UNKNOWN 集 ───────────────────────────────────────────────────
    known = {r["base_concept"] for r in rows}
    unk = []
    p = os.path.join(raw_catalog_dir, "01_field_catalog", "eicu_customlab.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
            nm = (r.get("labothername") or r.get("labname") or
                  list(r.values())[0] or "").strip()
            if nm:
                unk.append(("eicu", "customLab", nm, "站点自定义化验名"))
    p = os.path.join(raw_catalog_dir, "01_field_catalog", "eicu_infusiondrug.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
            nm = (r.get("drugname") or list(r.values())[0] or "").strip()
            if nm and not any(k in nm.lower() for k in MEDICATION):
                unk.append(("eicu", "infusionDrug", nm, "输注药名, 不在概念目录内"))
    # MIMIC-III CareVue 侧的 UNKNOWN 源: Free Form Intake (自由文本入量描述, 明显在概念库外),
    # 与 MIMIC-IV 的 Skin-Impairment / Access Lines 同性质。
    # ⚠️ 这是**仲裁前的近似**; 最终 UNKNOWN 集应来自 worksheets 中人工标为 UNKNOWN 的字段。
    p = os.path.join(raw_catalog_dir, "01_field_catalog", "m3_d_items.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
            if (r.get("DBSOURCE") or "").lower() == "carevue" and \
                    (r.get("CATEGORY") or "") in ("Free Form Intake",):
                unk.append(("mimic-iii", "D_ITEMS:Free Form Intake",
                            r.get("LABEL", ""), "自由文本入量描述, 目标概念库外"))
    p = os.path.join(raw_catalog_dir, "01_field_catalog", "m4_d_items.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
            if (r.get("category") or "") in ("Skin - Impairment", "Skin-Impairment",
                                             "Access Lines - Invasive", "Access Lines"):
                unk.append(("mimic-iv", "d_items:" + r["category"],
                            r.get("label", ""), "目标概念库外的类别"))
    seen, uniq = set(), []
    for u in unk:
        if u[2] and u[2].lower() not in seen and u[2].lower() not in known:
            seen.add(u[2].lower()); uniq.append(u)
    with open(F("unknown_set.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["db", "src_table", "field_name", "reason"])
        w.writerows(uniq)

    by_group = collections.Counter(r["group"] for r in rows)
    by_status = collections.Counter(r["status"] for r in rows)
    return {"concepts_total": len(rows), "by_group": dict(by_group),
            "by_status": dict(by_status), "unknown_set": len(uniq),
            "quota": GROUPS}
