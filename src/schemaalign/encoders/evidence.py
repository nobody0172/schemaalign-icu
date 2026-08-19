# -*- coding: utf-8 -*-
"""证据视图: 把字段的结构与统计属性转成**离散 token**。

E24 的负面结果证明: 把 p01/p50/p99、频率、缺失率**以自由文本拼进 FieldCard**,
会让相似度携带域特异信息 —— 源域 R@1 最高 (63.2), 但 CareVue precision 崩到 34.5。
执行文档 §3.1 L104 的要求正是为此: 「分位数与频率用**分桶后的离散 token**,
不要直接喂浮点数 —— 这样跨库尺度差异不会污染嵌入」。

九个属性 token (C1: 不含任何主键):
  unit_class          单位**量纲**类 (不是单位字符串) —— 量纲跨库不变, 字符串不然
  dtype               numeric / categorical / mixed / unknown
  table_provenance    来源族 (laboratory / bedside_nursing / monitor / ...)
  category            粗粒度概念组, 由关键词规则从各库各自的 category 映射而来
  p01 / median / p99  log10 分位分桶
  obs_freq            每 stay 观测次数, log10 分位分桶
  missing_rate        缺失率, 等距分桶

C4: **所有分桶边界只在 MIMIC-IV 训练分割上估计**, 目标域沿用同一套边界。
"""
import json
import math
import re

from ..gates.rules import provenance_family
from ..units.from_name import effective_unit
from ..units.table import default_table

__all__ = ["EvidenceVocab", "FIELDS"]

# 必须与 facets/model.py 的 EVIDENCE_FIELDS 逐字一致 (执行文档 §3.1 L104 的写法)
FIELDS = ("unit_class", "dtype", "table_provenance", "category",
          "p01_bucket", "median_bucket", "p99_bucket",
          "obs_freq_bucket", "missing_bucket")

_DTYPE = {"numeric": 0, "categorical": 1, "mixed": 2}
_PROV = {"laboratory": 0, "bedside_nursing": 1, "monitor": 2, "respiratory": 3,
         "prescription": 4, "administration": 5}
# 各库的 category 词表互不相同, 用关键词规则映射到粗粒度组 (域不变)
_CATRULES = [
    (re.compile(r"lab|chem|hema|coag|blood ?gas|abg|enzyme|urine|csf|micro", re.I), "lab"),
    (re.compile(r"vital|hemodynam|cardio|bp|pressure|pulse|temperature", re.I), "vital"),
    (re.compile(r"resp|vent|airway|oxygen|o2|pulmon", re.I), "respiratory"),
    (re.compile(r"med|drug|infus|prescri|solution|fluid|intake", re.I), "medication"),
    (re.compile(r"neuro|gcs|sedat|pain|deliri", re.I), "neuro"),
    (re.compile(r"skin|access|line|care|assess|position|safety|activity", re.I), "care"),
]
_CAT = {"lab": 0, "vital": 1, "respiratory": 2, "medication": 3, "neuro": 4,
        "care": 5, "other": 6}


def _cat_of(raw):
    s = (raw or "").strip()
    if not s:
        return "other"
    for rx, g in _CATRULES:
        if rx.search(s):
            return g
    return "other"


def _unit_class(row):
    src, u, _ = effective_unit(row.get("unit_observed") or None,
                               (row.get("label") or row.get("field_key") or ""))
    if u is None:
        return "missing"
    d = default_table().dimension(u)
    return d or "other"


def _safe(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


class EvidenceVocab(object):
    """在 MIMIC-IV 训练分割上 fit, 之后对所有库 transform。"""

    def __init__(self, n_bucket=10):
        self.n_bucket = n_bucket
        self.units, self.cats = {}, dict(_CAT)
        self.edges = {}

    # ---- fit ----
    def fit(self, rows):
        us = sorted({_unit_class(r) for r in rows})
        self.units = {u: i for i, u in enumerate(us)}
        self.units.setdefault("missing", len(self.units))
        for key, col, logscale in (("p01_bucket", "p01", True),
                                   ("median_bucket", "p50", True),
                                   ("p99_bucket", "p99", True),
                                   ("obs_freq_bucket", "obs_per_key", True),
                                   ("missing_bucket", "missing_rate", False)):
            vals = [_safe(r.get(col)) for r in rows]
            vals = [v for v in vals if v is not None]
            if logscale:
                vals = [math.log10(abs(v) + 1e-6) for v in vals]
            vals.sort()
            if not vals:
                self.edges[key] = []
                continue
            q = self.n_bucket
            self.edges[key] = [vals[int(len(vals) * i / q)] for i in range(1, q)]
        return self

    # ---- transform ----
    def _bucket(self, key, x, logscale):
        v = _safe(x)
        if v is None:
            return self.n_bucket            # 缺失单独占一档
        if logscale:
            v = math.log10(abs(v) + 1e-6)
        e = self.edges.get(key, [])
        lo = 0
        for b in e:
            if v >= b:
                lo += 1
            else:
                break
        return min(lo, self.n_bucket - 1)

    def transform(self, row):
        """-> {属性名: 整数 id}"""
        return {
            "unit_class": self.units.get(_unit_class(row), self.units.get("missing", 0)),
            "dtype": _DTYPE.get(row.get("dtype_inferred") or "", 3),
            "table_provenance": _PROV.get(provenance_family(row.get("src_table")), 6),
            "category": self.cats.get(_cat_of(row.get("dict_category")), self.cats["other"]),
            "p01_bucket": self._bucket("p01_bucket", row.get("p01"), True),
            "median_bucket": self._bucket("median_bucket", row.get("p50"), True),
            "p99_bucket": self._bucket("p99_bucket", row.get("p99"), True),
            "obs_freq_bucket": self._bucket("obs_freq_bucket", row.get("obs_per_key"), True),
            "missing_bucket": self._bucket("missing_bucket", row.get("missing_rate"), False),
        }

    def sizes(self):
        return {"unit_class": max(len(self.units), 1), "dtype": 4,
                "table_provenance": 7, "category": len(self.cats),
                "p01_bucket": self.n_bucket + 1, "median_bucket": self.n_bucket + 1,
                "p99_bucket": self.n_bucket + 1, "obs_freq_bucket": self.n_bucket + 1,
                "missing_bucket": self.n_bucket + 1}

    def save(self, path):
        json.dump({"n_bucket": self.n_bucket, "units": self.units,
                   "cats": self.cats, "edges": self.edges},
                  open(path, "w"), indent=1)

    @classmethod
    def load(cls, path):
        d = json.load(open(path))
        v = cls(d["n_bucket"]); v.units = d["units"]; v.cats = d["cats"]; v.edges = d["edges"]
        return v
