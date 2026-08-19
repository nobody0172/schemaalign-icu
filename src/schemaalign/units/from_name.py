# -*- coding: utf-8 -*-
"""从字段名里抽单位 —— 确定性正则, 无学习成分 (C6)。

**为什么必须有这一步**: 实测 (证据台账 E2) eICU 的 nurseCharting / respiratoryCharting /
vitalPeriodic / vitalAperiodic 四张表共 319 个字段、7.3 亿行, **单位列全为空**;
单位唯一的载体是字段名字符串本身, 例如 `Temperature (C)` / `Temperature (F)` /
`MAP (mmHg)` / `platelets x 1000`。不抽名内单位, V_unit 在这些字段上永远只能判 0.5,
指南 §3.1 Table 1 的难例 #1 也就无法成立。

抽取规则全部可打印, 且**只在 unit_observed 缺失时启用**, 不覆盖实测单位。
"""
import re

from .table import normalize_unit

__all__ = ["extract_unit_from_name", "effective_unit"]

# (正则, 规范单位, 说明) —— 顺序即优先级
_RULES = [
    (re.compile(r"\(\s*(?:deg\s*)?c\s*\)", re.I), "degC", "名内括号 (C)"),
    (re.compile(r"\(\s*(?:deg\s*)?f\s*\)", re.I), "degF", "名内括号 (F)"),
    (re.compile(r"\(\s*mmhg\s*\)", re.I), "mmHg", "名内括号 (mmHg)"),
    (re.compile(r"\(\s*cmh2o\s*\)", re.I), "cmH2O", "名内括号 (cmH2O)"),
    (re.compile(r"\(\s*%\s*\)|\bpercent\b", re.I), "%", "名内百分号"),
    (re.compile(r"\(\s*l/min\s*\)|\blpm\b", re.I), "L/min", "名内流量"),
    (re.compile(r"\(\s*ml/hr?\s*\)", re.I), "mL/hr", "名内流速"),
    (re.compile(r"\(\s*bpm\s*\)|\bbeats?/min\b", re.I), "bpm", "名内心率单位"),
    (re.compile(r"\(\s*mg/dl\s*\)", re.I), "mg/dL", "名内质量浓度"),
    (re.compile(r"\(\s*mmol/l\s*\)", re.I), "mmol/L", "名内摩尔浓度"),
    (re.compile(r"\(\s*meq/l\s*\)", re.I), "mEq/L", "名内当量浓度"),
    (re.compile(r"\bx\s*1000\b", re.I), "K/uL", "名内 'x 1000' = 千计数/uL"),
    (re.compile(r"\bmcg/kg/min\b", re.I), "mcg/kg/min", "药名内嵌剂量率"),
    (re.compile(r"\bmcg/min\b", re.I), "mcg/min", "药名内嵌剂量率"),
    (re.compile(r"\bunits?/hr?\b", re.I), "units/hr", "药名内嵌剂量率"),
    (re.compile(r"\binch(es)?\b", re.I), "inch", "名内长度"),
    (re.compile(r"\bkg\b", re.I), "kg", "名内质量"),
    (re.compile(r"\blbs?\b", re.I), "lb", "名内质量"),
]


def extract_unit_from_name(name):
    """返回 (规范单位, 依据) ; 抽不到返回 (None, None)。"""
    if not name:
        return None, None
    for rx, unit, why in _RULES:
        if rx.search(str(name)):
            return unit, "%s: 命中 /%s/" % (why, rx.pattern)
    return None, None


def effective_unit(unit_observed, raw_name):
    """
    单位的最终取值与来源等级:
        ('measured', u)     实测 valueuom 众数 —— 最可信
        ('from_name', u)    名内抽取 —— 次可信, 仅在实测缺失时启用
        ('missing', None)   两者皆无 -> V_unit 只能判 0.5
    """
    u = normalize_unit(unit_observed)
    if u:
        return "measured", u, "实测 valueuom 众数"
    u2, why = extract_unit_from_name(raw_name)
    if u2:
        return "from_name", u2, why
    return "missing", None, "实测单位与名内单位皆缺失"
