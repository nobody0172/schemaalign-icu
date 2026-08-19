# -*- coding: utf-8 -*-
"""Gate G3 验收 —— 指南 §3.1 Table 1 的 5 条 + 实施方案 §5.2 的 12 条难例。

执行文档 §5 T3:「这 17 条测试用例是论文 Table 1 与 Table 3 的直接支撑, 必须全绿。」
每个 FieldSpec 的 p01/p50/p99 与行数均取自实测 (data/field_catalog/, 证据台账 E5)。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from schemaalign.gates.rules import FieldSpec as F, gate_all, measurement_method
from schemaalign.units.from_name import effective_unit, extract_unit_from_name
from schemaalign.units.table import default_table

NC, LAB, VP = "eicu.nurseCharting", "eicu.lab", "eicu.vitalPeriodic"
M4C, M4L = "mimiciv.icu.chartevents", "mimiciv.hosp.labevents"
M4RX, M4IN = "mimiciv.hosp.prescriptions", "mimiciv.icu.inputevents"
M3C = "mimiciii.CHARTEVENTS"


# ═══ Table 1 / §5.2 难例 #1 —— 温度 C vs F ═══
def test_case01_temperature_c_vs_f_is_convertible_not_conflict():
    """单位写在名字里。正确判定是「可换算」而非「冲突」—— 同量纲, 必须先转换再合并。"""
    a = F("eicu", "x", "Temperature (C)", NC, None, "numeric", 35.1, 36.89, 38.6)
    b = F("eicu", "y", "Temperature (F)", NC, None, "numeric", 95.2, 98.40, 101.5)
    g = gate_all(a, b)
    assert g.v_unit == 0.0 and not g.hard_reject
    assert "convertible" in g.reasons[0]
    # 名内抽取必须生效 (单位列为空)
    assert extract_unit_from_name("Temperature (C)")[0] == "degC"
    assert extract_unit_from_name("Temperature (F)")[0] == "degF"
    # 换算后 p50 必须对上: 98.40 degF -> 36.89 degC
    assert default_table().convert(98.40, "degF", "degC") == pytest.approx(36.89, abs=0.02)


# ═══ #2 —— 无创 vs 有创血压 (实测 239,425 vs 40,349 stays) ═══
def test_case02_noninvasive_vs_invasive_bp_rejected():
    a = F("eicu", "x", "Non-Invasive BP Mean", NC, None, "numeric", 60, 78, 110)
    b = F("eicu", "y", "Invasive BP Mean", NC, None, "numeric", 55, 75, 115)
    g = gate_all(a, b)
    assert g.v_prov == 1.0 and g.hard_reject
    assert measurement_method("Non-Invasive BP Mean") == "noninvasive"
    assert measurement_method("Invasive BP Mean") == "invasive"


# ═══ #3 —— 同概念不同路径 (Heart Rate vs Pulse), 应放行交给语义层 ═══
def test_case03_heartrate_vs_pulse_not_rejected():
    a = F("eicu", "x", "Vital Signs|Heart Rate|Heart Rate", NC, None, "numeric", 52, 86, 140)
    b = F("eicu", "y", "Other Vital Signs and Infusions|Pulse|Value", NC, None, "numeric", 50, 84, 138)
    g = gate_all(a, b)
    assert not g.hard_reject, "同概念跨路径不应被门控拒绝, 应由语义相似度处理"


# ═══ #4 —— MAP vs Arterial Line MAP ═══
def test_case04_map_vs_arterial_line_map_flagged():
    a = F("eicu", "x", "MAP (mmHg)", NC, None, "numeric", 50, 76, 120)
    b = F("eicu", "y", "Arterial Line MAP (mmHg)", NC, None, "numeric", 48, 74, 118)
    g = gate_all(a, b)
    assert g.v_unit == 0.0                      # 名内 mmHg 均可抽取
    assert g.v_prov >= 0.5, "仅一侧标注测量方式 -> 至少判为无法判定, 不得判 0"


# ═══ #5 —— Temperature Location (分类被数值化, p99=103) vs Temperature (F) ═══
def test_case05_temperature_location_type_conflict():
    a = F("eicu", "x", "Temperature Location", NC, None, "categorical", 1, 3, 103, True)
    b = F("eicu", "y", "Temperature (F)", NC, None, "numeric", 95.2, 98.40, 101.5, True)
    g = gate_all(a, b)
    assert g.v_type == 1.0 and g.hard_reject


# ═══ #6 —— O2 Admin Device (设备名被编码成数值, p50=96.1) ═══
def test_case06_o2_admin_device_type_conflict():
    a = F("eicu", "x", "O2 Admin Device", NC, None, "categorical", 1, 96.1, 200, True)
    b = F("eicu", "y", "O2 Saturation", NC, None, "numeric", 88, 97, 100, True)
    assert gate_all(a, b).v_type == 1.0


# ═══ #7 —— CVP p99=288.5 mmHg 生理不可能值 (值域信号, 非硬拒) ═══
def test_case07_cvp_out_of_range_is_stat_signal_not_hard_reject():
    a = F("eicu", "x", "CVP", NC, None, "numeric", -2, 9, 288.5)
    b = F("mimic-iv", "y", "Central Venous Pressure", M4C, "mmHg", "numeric", 0, 10, 28)
    g = gate_all(a, b)
    assert not g.hard_reject, "值域异常属 S_stat 信号, 不在三个门控的硬拒范围内"
    assert a.p99 > b.p99 * 5, "实测 p99 相差一个量级, 应由 S_stat 惩罚"


# ═══ #8 —— bedside glucose(lab) vs Bedside Glucose(nurseCharting) ═══
def test_case08_lab_vs_bedside_provenance_conflict():
    a = F("eicu", "x", "bedside glucose", LAB, "mg/dL", "numeric", 70, 120, 400)
    b = F("eicu", "y", "Vital Signs|Bedside Glucose|Bedside Glucose", NC, None, "numeric", 70, 118, 395)
    g = gate_all(a, b)
    assert g.v_prov == 1.0 and g.hard_reject


# ═══ #9 —— eICU mmol/L vs MIMIC mEq/L (一价离子 1:1) ═══
@pytest.mark.parametrize("name", ["potassium", "sodium", "chloride", "bicarbonate"])
def test_case09_mmol_vs_meq_convertible(name):
    a = F("eicu", "x", name, LAB, "mmol/L", "numeric", 3.0, 4.0, 6.0)
    b = F("mimic-iv", "y", name, M4L, "mEq/L", "numeric", 3.1, 4.1, 6.1)
    g = gate_all(a, b)
    assert g.v_unit == 0.0 and "convertible" in g.reasons[0]
    assert default_table().convert(4.0, "mmol/L", "mEq/L") == pytest.approx(4.0)


# ═══ #10 —— anion gap 单位为 NULL -> 软约束, 不得硬拒 ═══
def test_case10_missing_unit_is_soft_not_conflict():
    a = F("eicu", "x", "anion gap", LAB, None, "numeric", 4, 9, 22)
    b = F("mimic-iv", "y", "Anion Gap", M4L, "mEq/L", "numeric", 5, 10, 23)
    g = gate_all(a, b)
    assert g.v_unit == 0.5, "单位缺失必须落到无法判定, 不能当成冲突"
    assert not g.hard_reject


# ═══ #11 —— 缩写与局部命名不应触发任何硬拒 ═══
@pytest.mark.parametrize("ename,mname,unit_e,unit_m", [
    ("platelets x 1000", "Platelet Count", None, "K/uL"),
    ("WBC x 1000", "White Blood Cells", None, "K/uL"),
    ("Hgb", "Hemoglobin", "g/dL", "g/dL"),
    ("Hct", "Hematocrit", "%", "%"),
    ("BUN", "Urea Nitrogen", "mg/dL", "mg/dL"),
])
def test_case11_abbreviations_pass_gate(ename, mname, unit_e, unit_m):
    a = F("eicu", "x", ename, LAB, unit_e, "numeric", 50, 200, 600)
    b = F("mimic-iv", "y", mname, M4L, unit_m, "numeric", 50, 210, 610)
    g = gate_all(a, b)
    assert not g.hard_reject, "缩写差异是语义层的事, 门控不得拒绝"


def test_case11b_x1000_name_unit_extraction():
    """'platelets x 1000' 的单位只能从名字里抽 (eICU lab 该项无单位)。"""
    assert extract_unit_from_name("platelets x 1000")[0] == "K/uL"
    src, u, _ = effective_unit(None, "platelets x 1000")
    assert (src, u) == ("from_name", "K/uL")


# ═══ #12 —— 处方 vs 实际给药 ═══
def test_case12_prescription_vs_administration_rejected():
    a = F("mimic-iv", "x", "Norepinephrine", M4RX, "mg", "numeric", 1, 4, 16)
    b = F("mimic-iv", "y", "Norepinephrine", M4IN, "mcg/kg/min", "numeric", 0.01, 0.08, 0.5)
    g = gate_all(a, b)
    assert g.v_prov == 1.0 and g.hard_reject


# ═══ 附加: 量纲明确不同必须硬拒 ═══
def test_dimension_conflict_hard_rejects():
    a = F("mimic-iv", "x", "Arterial BP mean", M4C, "mmHg", "numeric", 50, 76, 120)
    b = F("mimic-iv", "y", "Temperature Celsius", M4C, "degC", "numeric", 35, 36.9, 39)
    g = gate_all(a, b)
    assert g.v_unit == 1.0 and g.hard_reject


# ═══ 附加: 实测单位优先于名内抽取 ═══
def test_measured_unit_wins_over_name():
    src, u, _ = effective_unit("degC", "Temperature (F)")
    assert (src, u) == ("measured", "degC")


# ═══ 附加: V_prov 硬拒开关 —— 两份规格文档口径不一致 ═══
def test_prov_hard_reject_switch():
    a = F("mimic-iv", "x", "Norepinephrine", M4RX, "mg", "numeric", 1, 4, 16)
    b = F("mimic-iv", "y", "Norepinephrine", M4IN, "mg", "numeric", 1, 4, 16)
    assert gate_all(a, b, hard_reject_prov=True).hard_reject          # 执行文档 §5 T3 口径
    assert not gate_all(a, b, hard_reject_prov=False).hard_reject     # 指南 §2.1 口径


# ═══ 附加: 规则必须可打印 (C6) ═══
def test_rules_are_printable():
    a = F("eicu", "x", "Temperature (C)", NC, None, "numeric", 35, 36.9, 38.6)
    b = F("eicu", "y", "Temperature (F)", NC, None, "numeric", 95, 98.4, 101.5)
    txt = gate_all(a, b).explain()
    assert "V_unit" in txt and "V_type" in txt and "V_prov" in txt
    assert len(txt.splitlines()) >= 4


# ═══ concept_mode: 字段→概念 匹配时表来源族冲突降为软约束 ═══
def test_concept_mode_softens_table_family_conflict():
    """概念不绑定单一表来源: 血糖既可来自化验也可来自床旁。
    字段→字段仍硬拒 (难例 #8), 字段→概念只软惩罚。"""
    a = F("eicu", "x", "bedside glucose", LAB, "mg/dL", "numeric", 70, 120, 400)
    b = F("mimic-iv", "y", "Glucose finger stick", M4C, "mg/dL", "numeric", 70, 118, 395)
    assert gate_all(a, b, concept_mode=False).v_prov == 1.0     # 字段→字段: 冲突
    assert gate_all(a, b, concept_mode=True).v_prov == 0.5      # 字段→概念: 无法判定


def test_concept_mode_still_rejects_method_conflict():
    """测量方式冲突在两种模式下都必须判 1 —— 方式在两侧都能从名字确定性抽取。"""
    a = F("eicu", "x", "Non-Invasive BP Mean", NC, None, "numeric", 60, 78, 110)
    b = F("eicu", "y", "Invasive BP Mean", NC, None, "numeric", 55, 75, 115)
    assert gate_all(a, b, concept_mode=True).v_prov == 1.0
    assert gate_all(a, b, concept_mode=False).v_prov == 1.0


def test_concept_mode_still_rejects_prescription_vs_administration():
    a = F("mimic-iv", "x", "Norepinephrine", M4RX, "mg", "numeric", 1, 4, 16)
    b = F("mimic-iv", "y", "Norepinephrine", M4IN, "mcg/kg/min", "numeric", 0.01, 0.08, 0.5)
    # 处方 vs 给药即使在概念模式下也应保持硬拒 —— 二者是不同的临床事件
    assert gate_all(a, b, concept_mode=False).v_prov == 1.0


# ═══ V_type 只在两侧均为字典声明时硬拒 ═══
def test_vtype_hard_reject_only_when_both_declared():
    """推断出的类型冲突不得硬拒 —— 实测它在 gold 对上造成 23/34 的误拒。"""
    a = F("eicu", "x", "Temperature Location", NC, None, "categorical", 1, 3, 103)
    b = F("mimic-iv", "y", "Temperature C", M4C, "degC", "numeric", 35, 36.9, 39)
    a_dec = a._replace(dtype_declared=True)
    b_dec = b._replace(dtype_declared=True)
    assert gate_all(a_dec, b_dec).v_type == 1.0        # 两侧声明 -> 硬拒
    assert gate_all(a, b_dec).v_type == 0.5            # 一侧推断 -> 软约束
    assert gate_all(a, b).v_type == 0.5


# ═══ V_specimen —— 指南 §7.4 的 specimen 维（第二轮仲裁暴露的缺口） ═══
M4L_ = "mimiciv.hosp.labevents"


def _lab(name, fluid, unit="g/dL", p50=3.5):
    return F("mimic-iv", "k", name, M4L_, unit, "numeric", 1.0, p50, 6.0, True, fluid)


def test_specimen_blood_vs_ascites_rejected():
    """最强的难例: 名字相同、单位相同、值域重叠, **只有标本能区分**。"""
    a = _lab("Albumin", "Blood", "g/dL", 3.5)
    b = _lab("Albumin, Ascites", "Ascites", "g/dL", 1.2)
    g = gate_all(a, b, concept_mode=True)
    assert g.v_unit == 0.0, "单位相同, 单位门控看不出问题"
    assert g.v_type == 0.0, "类型相同, 类型门控也看不出"
    assert g.v_specimen == 1.0 and g.hard_reject, "只有 V_specimen 能挡住"


@pytest.mark.parametrize("fluid,expect", [
    ("Blood", "blood"), ("Serum", "blood"), ("Urine", "urine"),
    ("Ascites", "body_fluid"), ("Pleural", "body_fluid"),
    ("Cerebrospinal Fluid (CSF)", "csf"), ("Stool", "stool"), ("", None)])
def test_specimen_class_mapping(fluid, expect):
    from schemaalign.gates.rules import specimen_class
    assert specimen_class(fluid, None) == expect


def test_specimen_falls_back_to_name():
    """无 fluid 列时从字段名抽取 (eICU 无字典)。"""
    from schemaalign.gates.rules import specimen_class
    assert specimen_class(None, "Glucose, Pleural") == "body_fluid"
    assert specimen_class(None, "Protein, Urine") == "urine"
    assert specimen_class(None, "Heart Rate") is None


def test_specimen_missing_is_soft():
    a = _lab("Glucose", None, "mg/dL", 120)
    b = _lab("Glucose", None, "mg/dL", 118)
    g = gate_all(a, b, concept_mode=True)
    assert g.v_specimen == 0.5 and not g.hard_reject
