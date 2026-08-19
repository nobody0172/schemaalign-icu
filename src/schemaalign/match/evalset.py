# -*- coding: utf-8 -*-
"""T4 · 评测集构造 —— 所有基线与本方法共用同一套输入, 保证可比。

评测任务: 给定目标库的一个字段, 在概念目录 (C 个概念) 中排序, 或判为 UNKNOWN。

正例: gold_pairs.csv 里的 (db, field_key) -> base_concept
负例: unknown_set.csv 中能在该库字段目录里找到的字段 (真实存在, 非人造)

⚠️ 概念侧只用 `base_concept` 归一名, **不引入任何来自目标库字段名的别名** ——
   否则 Exact-name 基线会看到答案, 指标虚高。
"""
import collections
import csv
import os
import re

__all__ = ["EvalSet", "normalize_name", "load_evalset"]

_ABBR = {
    "hgb": "hemoglobin", "hct": "hematocrit", "wbc": "white blood cells",
    "rbc": "red blood cells", "bun": "urea nitrogen", "hr": "heart rate",
    "rr": "respiratory rate", "bp": "blood pressure", "temp": "temperature",
    "spo2": "oxygen saturation", "sao2": "oxygen saturation", "o2 sat": "oxygen saturation",
    "sbp": "systolic blood pressure", "dbp": "diastolic blood pressure",
    "map": "mean arterial pressure", "mbp": "mean blood pressure",
    "inr": "international normalized ratio", "ptt": "partial thromboplastin time",
    "pt": "prothrombin time", "gcs": "glasgow coma scale",
    "alt": "alanine aminotransferase", "ast": "aspartate aminotransferase",
    "alp": "alkaline phosphatase", "ldh": "lactate dehydrogenase",
    "cvp": "central venous pressure", "icp": "intracranial pressure",
    "peep": "positive end expiratory pressure", "fio2": "fraction of inspired oxygen",
}
_SYM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(s):
    """小写 -> 去符号 -> 压空格 -> 常见缩写归一 (执行文档 §5 T4 的 Exact 基线定义)。"""
    if not s:
        return ""
    t = str(s).lower()
    t = t.split("|")[-1]                     # eICU 三级键值取最后一段
    t = _SYM.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    if t in _ABBR:
        return _ABBR[t]
    toks = [_ABBR.get(w, w) for w in t.split()]
    return " ".join(toks)


class EvalSet(object):
    def __init__(self, db, concepts, items):
        self.db = db
        self.concepts = concepts            # [base_concept]
        self.items = items                  # [{field_key, raw_name, gold, spec}]

    def __len__(self):
        return len(self.items)

    def summary(self):
        pos = sum(1 for i in self.items if i["gold"] is not None)
        return {"db": self.db, "n_concepts": len(self.concepts),
                "n_fields": len(self.items), "n_positive": pos,
                "n_unknown": len(self.items) - pos}


def _finish(db, concepts, cat, gold, unk, split):
    """统一出口: 组装 items, 并按需做 C4 合规的确定性切分。

    字段本身没有 split 属性 (split 是患者级的), 故按 field_key 的 CRC32 做确定性划分,
    保证 θ_open 的标定集 (val) 与主结果评测集 (test) 在**字段层面**不重叠。
    """
    import zlib
    items = []
    for k in list(gold) + unk:
        c = cat[k]
        # C1: raw_name 只用字典 label; 无 label 时字段名本身就是名字 (eICU/处方)
        items.append({"field_key": k, "raw_name": (c.get("label") or k).split("|")[-1],
                      "gold": gold.get(k), "row": c})
    if split:
        keep = {"train": lambda b: b < 7, "val": lambda b: b == 7,
                "test": lambda b: b >= 8}[split]
        items = [i for i in items if keep(zlib.crc32(i["field_key"].encode()) % 10)]
    return EvalSet(db, concepts, items)


def load_evalset(gold_dir, catalog_dir, db, catalog_file, max_unknown=400, split=None,
                 cohort_split_file=None):
    """split: 仅对 MIMIC-IV 有效, 取 'train'/'val'/'test' 的字段子集用于 C4 合规的阈值标定。
    字段本身没有 split 属性, 故按 gold 对的**概念**做确定性哈希划分, 保证标定集与评测集不重叠。"""
    concepts = sorted({r["base_concept"] for r in csv.DictReader(
        open(os.path.join(gold_dir, "concepts.csv"), newline="", encoding="utf-8"))})
    cat = {r["field_key"]: r for r in csv.DictReader(
        open(os.path.join(catalog_dir, catalog_file), newline="", encoding="utf-8"))}

    gold = {}
    for r in csv.DictReader(open(os.path.join(gold_dir, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] == db and r["field_key"] in cat:
            gold[r["field_key"]] = r["base_concept"]

    # 优先用**逐字段人工过目**产出的 UNKNOWN (仲裁结果), 它比自动推导的候选集可信得多;
    # 没有时回退到自动候选集。
    adj = os.path.join(gold_dir, "unknown_set_adjudicated.csv")
    unk = []
    if os.path.exists(adj):
        for r in csv.DictReader(open(adj, newline="", encoding="utf-8")):
            if r["db"] == db and r["field_key"] in cat and r["field_key"] not in gold:
                unk.append(r["field_key"])
        unk = sorted(set(unk), key=lambda k: -int(cat[k]["n_rows"] or 0))[:max_unknown]
        return _finish(db, concepts, cat, gold, unk, split)
    for r in csv.DictReader(open(os.path.join(gold_dir, "unknown_set.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != db:
            continue
        for k, cr in cat.items():
            lab = (cr.get("label") or k)
            if r["field_name"] in (k, lab, k.split("|")[-1], lab.split("|")[-1]):
                if k not in gold:
                    unk.append(k)
                break
    # 负例按观测行数取前 max_unknown, 避免长尾稀疏字段主导开放集指标
    unk = sorted(set(unk), key=lambda k: -int(cat[k]["n_rows"] or 0))[:max_unknown]

    return _finish(db, concepts, cat, gold, unk, split)
