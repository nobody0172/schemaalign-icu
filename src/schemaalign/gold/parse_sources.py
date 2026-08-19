# -*- coding: utf-8 -*-
"""T2 · 五源解析 —— 从公开 SQL 里抽出 (库, 原始字段标识, 规范概念名) 三元组。

执行文档 §5 T2: 「不要从零标注」。三份互相独立、专家策展的公开映射:
  S1 mimic-code/mimic-iv/concepts_duckdb   MIMIC-IV itemid -> 概念
  S2 mimic-code/mimic-iii/concepts         MIMIC-III itemid -> 概念 (含 CareVue 段编号)
  S3 eicu-code/concepts/pivoted            eICU labname / nurseCharting 三元组 -> 概念
另两份在服务器上, 只提供概念词表(无 itemid), 作为交叉校验:
  S4 temporal-respiratory-support_1.1      63 列规范概念名
  S5 MIMIC-sepsis patient_timeseries_v4    56 列规范变量名

⚠️ C1: 解析出的 itemid **只用于构造 gold 与下游取数, 绝不进入 FieldCard**。

四种源码模式 (逐一核实过, 见 docs/plans/):
  P1 MIMIC-IV 自动生成 : CASE WHEN itemid = 50862 ... END) AS albumin
  P2 MIMIC-III vitalid : when itemid in (211,220045) and ... then 1 -- HeartRate
  P3 MIMIC-III label   : WHEN itemid = 50868 THEN 'ANION GAP'
  P4 eICU labname      : MAX(case when labname = 'albumin' then ... end) as albumin
  P5 eICU 三级键值     : case when nursingchartcelltypevallabel='Heart Rate'
                              and nursingchartcelltypevalname='Heart Rate' ... end as heartrate
"""
import os
import re

__all__ = ["parse_all", "normalize_concept", "Triple"]


class Triple(object):
    __slots__ = ("db", "field_key", "concept_raw", "concept", "src_file", "pattern")

    def __init__(self, db, field_key, concept_raw, src_file, pattern):
        self.db = db
        self.field_key = str(field_key)
        self.concept_raw = concept_raw
        self.concept = normalize_concept(concept_raw)
        self.src_file = src_file
        self.pattern = pattern

    def as_row(self):
        return (self.db, self.field_key, self.concept, self.concept_raw,
                self.src_file, self.pattern)


# ── 概念名归一 ────────────────────────────────────────────────────────────
# 各源用了不同写法(HeartRate / heartrate / heart_rate / HEART RATE), 先拆词再合并同义。
_SYN = {
    "heartrate": "heart_rate", "hr": "heart_rate", "pulse": "heart_rate",
    "resprate": "respiratory_rate", "respiratoryrate": "respiratory_rate",
    "resp_rate": "respiratory_rate", "rr": "respiratory_rate",
    "sysbp": "sbp", "systolic": "sbp", "nibp_systolic": "sbp_noninvasive",
    "systemicsystolic": "sbp_invasive", "ibp_systolic": "sbp_invasive",
    "diasbp": "dbp", "diastolic": "dbp", "nibp_diastolic": "dbp_noninvasive",
    "systemicdiastolic": "dbp_invasive", "ibp_diastolic": "dbp_invasive",
    "meanbp": "mbp", "nibp_mean": "mbp_noninvasive", "systemicmean": "mbp_invasive",
    "ibp_mean": "mbp_invasive", "mbp_ni": "mbp_noninvasive",
    "spo2": "spo2", "o2saturation": "spo2", "o2_saturation": "spo2", "sao2": "spo2",
    "temperature": "temperature", "tempc": "temperature", "tempf": "temperature",
    "temp_c": "temperature", "temp_f": "temperature",
    "glucose": "glucose", "bedsideglucose": "glucose_bedside",
    "hematocrit": "hematocrit", "hct": "hematocrit",
    "hemoglobin": "hemoglobin", "hgb": "hemoglobin",
    "platelet": "platelets", "platelets": "platelets",
    "wbc": "wbc", "whitebloodcell": "wbc",
    "bun": "bun", "ureanitrogen": "bun",
    "aniongap": "anion_gap", "totalco2": "bicarbonate", "co2": "bicarbonate",
    "inr": "inr", "ptinr": "inr", "pt": "pt", "ptt": "ptt",
    "alt": "alt", "altsgpt": "alt", "ast": "ast", "astsgot": "ast",
    "alp": "alkaline_phosphatase", "alkalinephos": "alkaline_phosphatase",
    "bilirubin": "bilirubin_total", "totalbilirubin": "bilirubin_total",
    "gcs": "gcs_total", "o2flow": "o2_flow", "tidalvolume": "tidal_volume",
    "hco3": "bicarbonate", "ventilationrate": "respiratory_rate_set",
    "norepinephrine": "norepinephrine", "epinephrine": "epinephrine",
    "dopamine": "dopamine", "dobutamine": "dobutamine", "vasopressin": "vasopressin",
    "ratenorepinephrine": "norepinephrine", "rateepinephrine": "epinephrine",
    "ratedopamine": "dopamine", "ratedobutamine": "dobutamine",
    "pao2": "po2", "po2": "po2", "paco2": "pco2", "pco2": "pco2",
    "ph": "ph", "fio2": "fio2", "peep": "peep", "baseexcess": "base_excess",
    "basedeficit": "base_deficit", "lactate": "lactate",
    "gcs": "gcs_total", "gcstotal": "gcs_total", "gcseyes": "gcs_eyes",
    "gcsmotor": "gcs_motor", "gcsverbal": "gcs_verbal",
    "urineoutput": "urine_output", "uo": "urine_output",
    "cvp": "cvp", "icp": "icp", "etco2": "etco2",
    "weight": "weight", "height": "height",
}
_STRIP = re.compile(r"(_min|_max|_mean|_median|_first|_last|_avg|_24hours|_value)$")


def normalize_concept(raw):
    if raw is None:
        return None
    s = str(raw).strip().strip("'\"").lower()
    s = re.sub(r"[\s\-/().,]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    for _ in range(3):                       # 聚合后缀可叠加, 反复剥离
        s2 = _STRIP.sub("", s)
        if s2 == s:
            break
        s = s2
    key = s.replace("_", "")
    return _SYN.get(key, _SYN.get(s, s))


# ── P1: MIMIC-IV concepts_duckdb ─────────────────────────────────────────
_P1 = re.compile(
    r"CASE\s+WHEN\s+itemid\s*(?:=\s*(\d+)|IN\s*\(([^)]*)\))(.*?)END\s*\)?\s*AS\s+([A-Za-z_][\w]*)",
    re.I | re.S)


def _parse_p1(text, db, fname):
    out = []
    for m in _P1.finditer(text):
        ids = [m.group(1)] if m.group(1) else re.findall(r"\d+", m.group(2) or "")
        for i in ids:
            out.append(Triple(db, i, m.group(4), fname, "P1"))
    return out


# ── P2: MIMIC-III vitalid + 行尾注释 ─────────────────────────────────────
_P2 = re.compile(r"when\s+itemid\s+in\s*\(([^)]*)\).*?then\s+\d+\s*--\s*([^\n,]+)", re.I)


def _parse_p2(text, db, fname):
    out = []
    for m in _P2.finditer(text):
        name = m.group(2).split(",")[0].strip()
        for i in re.findall(r"\d+", m.group(1)):
            out.append(Triple(db, i, name, fname, "P2"))
    return out


# ── P3: MIMIC-III  WHEN itemid = N THEN 'LABEL' ─────────────────────────
_P3 = re.compile(r"WHEN\s+itemid\s*=\s*(\d+)\s+THEN\s+'([^']+)'", re.I)


def _parse_p3(text, db, fname):
    return [Triple(db, m.group(1), m.group(2), fname, "P3")
            for m in _P3.finditer(text)]


# ── P4: eICU labname pivot ───────────────────────────────────────────────
_P4 = re.compile(
    r"case\s+when\s+labname\s*(?:=\s*'([^']+)'|in\s*\(([^)]*)\)).*?end\s*\)?\s*as\s+([A-Za-z_][\w]*)",
    re.I | re.S)


def _parse_p4(text, db, fname):
    out = []
    for m in _P4.finditer(text):
        names = [m.group(1)] if m.group(1) else re.findall(r"'([^']+)'", m.group(2) or "")
        for nm in names:
            out.append(Triple(db, nm, m.group(3), fname, "P4"))
    return out


# ── P5: eICU 三级键值 (vallabel + valname) ───────────────────────────────
_P5 = re.compile(
    r"nursingchartcelltypevallabel\s*=\s*'([^']+)'\s*and\s*"
    r"nursingchartcelltypevalname\s*=\s*'([^']+)'(.*?)end\s*(?:\)\s*)?as\s+([A-Za-z_][\w]*)",
    re.I | re.S)
_P5b = re.compile(
    r"respchartvaluelabel\s*(?:=\s*'([^']+)'|in\s*\(([^)]*)\))(.*?)end\s*(?:\)\s*)?as\s+([A-Za-z_][\w]*)",
    re.I | re.S)


def _parse_p5(text, db, fname):
    out = []
    for m in _P5.finditer(text):
        if len(m.group(3)) > 900:            # 跨越了多个 case 分支, 丢弃避免错配
            continue
        out.append(Triple(db, "%s|%s" % (m.group(1), m.group(2)), m.group(4), fname, "P5"))
    for m in _P5b.finditer(text):
        if len(m.group(3)) > 900:
            continue
        names = [m.group(1)] if m.group(1) else re.findall(r"'([^']+)'", m.group(2) or "")
        for nm in names:
            out.append(Triple(db, nm, m.group(4), fname, "P5b"))
    return out


PLAN = [
    # (相对 refs/ 的目录, 库标签, 解析器列表)
    # 执行文档 §3.3 给的是「最小集」; 实际扩到全部 concept 目录, 概念覆盖显著提高。
    ("mimic-code/mimic-iv/concepts_duckdb/measurement", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iv/concepts_duckdb/firstday", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iv/concepts_duckdb/medication", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iv/concepts_duckdb/treatment", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iv/concepts_duckdb/organfailure", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iv/concepts_duckdb/score", "mimic-iv", [_parse_p1, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/firstday", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/pivot", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/durations", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/fluid_balance", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/organfailure", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/severityscores", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("mimic-code/mimic-iii/concepts/cookbook", "mimic-iii", [_parse_p1, _parse_p2, _parse_p3]),
    ("eicu-code/concepts/pivoted", "eicu", [_parse_p4, _parse_p5]),
    ("eicu-code/concepts", "eicu", [_parse_p4, _parse_p5]),
]

def parse_all(refs_root):
    triples, per_file = [], {}
    for rel, db, parsers in PLAN:
        d = os.path.join(refs_root, rel)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".sql"):
                continue
            text = open(os.path.join(d, fn), encoding="utf-8", errors="ignore").read()
            got = []
            for p in parsers:
                got.extend(p(text, db, "%s/%s" % (rel.split("/")[-1], fn)))
            # 同一文件内去重
            seen, uniq = set(), []
            for t in got:
                k = (t.db, t.field_key, t.concept)
                if k not in seen:
                    seen.add(k)
                    uniq.append(t)
            per_file["%s:%s" % (db, fn)] = len(uniq)
            triples.extend(uniq)
    return triples, per_file
