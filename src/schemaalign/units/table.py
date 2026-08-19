# -*- coding: utf-8 -*-
"""T3 · 单位规范与换算 —— 确定性、可打印 (C6)。

设计要点:
  1. 换算表来自 `data/unit_tables/unit_conversion_v1.csv`, **每行必须有 source 列**
     指明出处 (执行文档 §5 T3)。代码里不硬编码任何换算系数。
  2. 三档关系: same / convertible / unknown / conflict, 直接喂给 V_unit 门控。
  3. **单位缺失不等于冲突**。实测 eICU 四张表 319 个字段单位可恢复率为 0
     (证据台账 E2), 缺失是主流情形, 必须落到 unknown 而非 conflict。
"""
import csv
import os
import re

__all__ = ["UnitTable", "normalize_unit", "default_table"]

_WS = re.compile(r"\s+")
# 同一单位在三库里的写法差异, 先归一再查表
_ALIAS = {
    "": None, "none": None, "null": None, "n/a": None, "?": None,
    "f": "degF", "°f": "degF", "degf": "degF", "fahrenheit": "degF",
    "c": "degC", "°c": "degC", "degc": "degC", "celsius": "degC",
    "mmhg": "mmHg", "mm hg": "mmHg", "torr": "mmHg",
    "cmh2o": "cmH2O", "cm h2o": "cmH2O", "cmh20": "cmH2O",
    "meq/l": "mEq/L", "meql": "mEq/L", "mmol/l": "mmol/L",
    "mg/dl": "mg/dL", "g/dl": "g/dL", "ug/dl": "ug/dL", "mcg/dl": "ug/dL",
    "k/ul": "K/uL", "k/mcl": "K/mcL", "10*3/ul": "10*3/uL", "10^3/ul": "K/uL",
    "in": "inch", "inches": "inch", "cm": "cm", "kg": "kg", "kgs": "kg",
    "lb": "lb", "lbs": "lb", "pounds": "lb",
    "bpm": "bpm", "beats/min": "bpm", "insp/min": "insp/min", "breaths/min": "bpm",
    "l/min": "L/min", "lpm": "L/min", "ml/hr": "mL/hr", "ml/h": "mL/hr",
    "mcg/kg/min": "mcg/kg/min", "mcg/min": "mcg/min", "units/hour": "units/hr",
    "%": "%", "percent": "%", "sec": "s", "seconds": "s",
}
# 量纲归属 —— 用于「明确冲突」判定
_DIM = {
    "degF": "temperature", "degC": "temperature",
    "mmHg": "pressure", "cmH2O": "pressure",
    "mEq/L": "concentration", "mmol/L": "concentration",
    "mg/dL": "mass_concentration", "g/dL": "mass_concentration", "ug/dL": "mass_concentration",
    "K/uL": "cell_count", "K/mcL": "cell_count", "10*3/uL": "cell_count",
    "inch": "length", "cm": "length", "kg": "mass", "lb": "mass",
    "bpm": "rate", "insp/min": "rate",
    "L/min": "flow", "mL/hr": "flow",
    "mcg/kg/min": "dose_rate", "mcg/min": "dose_rate", "units/hr": "dose_rate",
    "%": "fraction", "s": "time",
}


def normalize_unit(u):
    """任意写法 -> 规范单位串; 空/缺失 -> None。"""
    if u is None:
        return None
    s = _WS.sub(" ", str(u).strip()).lower()
    if s in _ALIAS:
        return _ALIAS[s]
    s2 = s.replace(" ", "")
    if s2 in _ALIAS:
        return _ALIAS[s2]
    return str(u).strip() or None


class UnitTable(object):
    def __init__(self, rows):
        self.rows = rows
        self._idx = {}
        for r in rows:
            a, b = normalize_unit(r["from_unit"]), normalize_unit(r["to_unit"])
            if a and b:
                self._idx[(a, b)] = r

    @classmethod
    def load(cls, path):
        with open(path, newline="", encoding="utf-8") as f:
            return cls(list(csv.DictReader(f)))

    def dimension(self, unit):
        u = normalize_unit(unit)
        if u is None:
            return None
        if u in _DIM:
            return _DIM[u]
        for r in self.rows:
            if normalize_unit(r["from_unit"]) == u and r.get("dimension"):
                return r["dimension"]
        return None

    def convert(self, value, from_unit, to_unit):
        """返回换算后的数值; 无法换算返回 None。"""
        a, b = normalize_unit(from_unit), normalize_unit(to_unit)
        if a is None or b is None:
            return None
        if a == b:
            return value
        r = self._idx.get((a, b))
        if r is None or not r.get("factor"):
            return None
        return (value + float(r.get("offset") or 0)) * float(r["factor"])

    def relation(self, u1, u2):
        """
        same        两侧单位相同
        convertible 表中有可审计换算 (可能带 condition)
        unknown     任一侧缺失, 或量纲未知 -> 软约束
        conflict    量纲明确不同 -> 硬拒
        """
        a, b = normalize_unit(u1), normalize_unit(u2)
        if a is None or b is None:
            return "unknown", "至少一侧单位缺失"
        if a == b:
            return "same", "单位相同: %s" % a
        r = self._idx.get((a, b)) or self._idx.get((b, a))
        if r is not None:
            cond = (r.get("condition") or "").strip()
            if not (r.get("factor") or "").strip():
                return "unknown", "条件可转(缺参数): %s -> %s [%s]" % (a, b, cond)
            return "convertible", "可换算 %s -> %s%s (出处: %s)" % (
                a, b, ("; 条件: " + cond) if cond else "", r.get("source", "")[:60])
        da, db = self.dimension(a), self.dimension(b)
        if da and db and da != db:
            return "conflict", "量纲不同: %s(%s) vs %s(%s)" % (a, da, b, db)
        return "unknown", "量纲未知或表中无换算: %s vs %s" % (a, b)


_DEFAULT = None


def default_table(path=None):
    """换算表路径解析顺序: 显式参数 -> 环境变量 SA_UNIT_TABLE -> 仓库默认位置。

    远端 `data/` 是只读数据集软链, 项目自有文件放在 `work/` 下, 故必须可覆盖。
    """
    global _DEFAULT
    if _DEFAULT is None:
        if path is None:
            path = os.environ.get("SA_UNIT_TABLE")
        if path is None:
            here = os.path.dirname(os.path.abspath(__file__))
            for cand in (os.path.join(here, "..", "..", "..", "data", "unit_tables",
                                      "unit_conversion_v1.csv"),
                         os.path.join(here, "..", "..", "..", "work", "unit_tables",
                                      "unit_conversion_v1.csv")):
                if os.path.exists(os.path.normpath(cand)):
                    path = cand
                    break
        if path is None:
            raise FileNotFoundError(
                "未找到单位换算表; 请设 SA_UNIT_TABLE 或放到 data|work/unit_tables/")
        _DEFAULT = UnitTable.load(os.path.normpath(path))
    return _DEFAULT
