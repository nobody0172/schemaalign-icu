# -*- coding: utf-8 -*-
"""T2 · 金标准构建 (执行文档 §5 T2, Gate G2)。

流程 (替代 idea v1 §10 步骤 3 的「从零标注」):
    5 源解析 -> (库, 原始字段标识, 规范概念名)
       ├─ 三库都覆盖且概念名一致        -> 高置信 gold, 自动通过
       ├─ 部分覆盖 / 概念名冲突          -> adjudication_queue.csv, 人工仲裁
       └─ 高频但任一源都未覆盖的字段      -> 人工补标 或 归入 UNKNOWN 候选

⚠️ 边界: 仲裁**不得**用字段名的字符串匹配来自动裁定 —— 那正是待评测的 Exact-name 基线,
   会让 gold 与基线同源, 基线虚高。本模块只负责: ①自动接受三源一致者
   ②为人工仲裁准备最大化的证据 ③核验解析出的字段在真实数据里是否存在。

C1: 这里的 itemid / labname 只用于构造 gold 与取数, 绝不进入 FieldCard。
"""
import collections
import csv
import os
import re

from .parse_sources import normalize_concept, parse_all

__all__ = ["ARTIFACTS", "base_and_method", "build"]

# 解析假阳性: SQL 里的临时列名/结构列, 不是临床概念
ARTIFACTS = {
    "valuenum", "itemid", "vitalid", "label", "comments", "decimal", "amount",
    "rate", "impute_abs", "line_number", "labresult", "specimen", "flow_rate",
    "vaso", "vaso_amount", "vaso_null", "vaso_stopped", "vaso_rate",
    "dialysis_type", "arterial_line",
}
_ARTIFACT_RE = re.compile(r"^inv\d+_(site|type)$")

# 测量方式修饰 (指南 §7.4: CanonicalConcept = (base_concept, measurement_method, ...))
_METHOD = [
    ("_noninvasive", "noninvasive"), ("_ni", "noninvasive"), ("nibp", "noninvasive"),
    ("_invasive", "invasive"), ("ibp", "invasive"),
    ("_bedside", "bedside"), ("_set", "set"), ("_observed", "observed"),
    ("_spontaneous", "spontaneous"), ("_total", "total"), ("_chartevents", "chartevents"),
]


def base_and_method(concept):
    """把 sbp_noninvasive -> (sbp, noninvasive)。指南 §7.4 的概念族分解。"""
    c = concept
    for suf, m in _METHOD:
        if suf.startswith("_") and c.endswith(suf):
            return c[: -len(suf)], m
        if not suf.startswith("_") and c == suf:
            return {"nibp": "bp", "ibp": "bp"}[c], m
    # 肺动脉/中心测压等本身就是独立概念, 不拆
    return c, "unspecified"


def _load_catalog(path):
    """T1.2 字段目录 -> {field_key: 行}"""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["field_key"]] = r
    return out


def _match_eicu(field_key, catalog):
    """eICU: P4 给的是 labname; P5 给的是 'vallabel|valname', 而目录键是 'cat|vallabel|valname'。"""
    if field_key in catalog:
        return [field_key]
    hits = [k for k in catalog if k.endswith("|" + field_key) or k == field_key]
    if hits:
        return hits
    if "|" in field_key:                    # 'Heart Rate|Heart Rate' -> 匹配后两段
        return [k for k in catalog if k.split("|", 1)[-1] == field_key]
    return []


def build(refs_root, catalog_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    triples, per_file = parse_all(refs_root)

    # ── 1. 过滤假阳性 + 分解 base_concept / method ──────────────────────
    kept, dropped = [], []
    for t in triples:
        if t.concept in ARTIFACTS or _ARTIFACT_RE.match(t.concept) or len(t.concept) <= 1:
            dropped.append(t)
            continue
        b, m = base_and_method(t.concept)
        kept.append((t.db, t.field_key, b, m, t.concept, t.src_file, t.pattern))

    # ── 2. 核验字段是否真的存在于队列数据中 (T1.2 目录) ────────────────
    CAT = {"mimic-iv": _load_catalog(os.path.join(catalog_dir, "field_catalog_m4.csv")),
           "mimic-iii": _load_catalog(os.path.join(catalog_dir, "field_catalog_m3cv.csv")),
           "eicu": _load_catalog(os.path.join(catalog_dir, "field_catalog_eicu.csv"))}
    verified, missing = [], []
    for db, fk, base, meth, craw, src, pat in kept:
        keys = _match_eicu(fk, CAT[db]) if db == "eicu" else ([fk] if fk in CAT[db] else [])
        if not keys:
            missing.append((db, fk, base, meth, src))
            continue
        for k in keys:
            row = CAT[db][k]
            verified.append({
                "db": db, "field_key": k, "base_concept": base, "method": meth,
                "concept_raw": craw, "src_file": src, "pattern": pat,
                "n_rows": row["n_rows"], "n_keys": row["n_keys"],
                "unit_observed": row["unit_observed"], "unit_recovery_rate": row["unit_recovery_rate"],
                "dtype_inferred": row["dtype_inferred"], "coverage": row["coverage"],
                "p01": row["p01"], "p50": row["p50"], "p99": row["p99"],
                "src_table": row["src_table"],
            })

    # ── 3. 交叉: 按 base_concept 统计库覆盖 ────────────────────────────
    cov = collections.defaultdict(set)
    for v in verified:
        cov[v["base_concept"]].add(v["db"])
    auto = {c for c, d in cov.items() if len(d) == 3}
    queue = {c for c, d in cov.items() if 1 <= len(d) <= 2}

    # ── 4. 落盘 ────────────────────────────────────────────────────────
    F = lambda n: os.path.join(out_dir, n)
    cols = ["db", "field_key", "base_concept", "method", "concept_raw", "src_table",
            "unit_observed", "unit_recovery_rate", "dtype_inferred", "p01", "p50", "p99",
            "n_rows", "n_keys", "coverage", "src_file", "pattern"]

    with open(F("gold_pairs_auto.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for v in sorted(verified, key=lambda x: (x["base_concept"], x["db"])):
            if v["base_concept"] in auto:
                w.writerow({k: v[k] for k in cols})

    with open(F("adjudication_queue.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols + ["dbs_covered", "dbs_missing", "verdict", "note"])
        w.writeheader()
        for v in sorted(verified, key=lambda x: (-len(cov[x["base_concept"]]),
                                                 x["base_concept"], x["db"])):
            if v["base_concept"] in queue:
                d = cov[v["base_concept"]]
                r = {k: v[k] for k in cols}
                r["dbs_covered"] = "+".join(sorted(d))
                r["dbs_missing"] = "+".join(sorted({"mimic-iv", "mimic-iii", "eicu"} - d))
                r["verdict"] = ""; r["note"] = ""
                w.writerow(r)

    with open(F("parsed_not_in_data.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["db", "field_key", "base_concept", "method", "src_file"])
        w.writerows(sorted(set(missing)))

    # ── 5. 三源两两一致率 (执行文档 §5 T2: 替代 Cohen's κ 的可复现数字) ──
    bydb = {d: {v["base_concept"] for v in verified if v["db"] == d}
            for d in ("mimic-iv", "mimic-iii", "eicu")}
    with open(F("source_agreement.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_a", "source_b", "concepts_a", "concepts_b",
                    "intersection", "union", "jaccard"])
        pairs = [("mimic-iv", "mimic-iii"), ("mimic-iv", "eicu"), ("mimic-iii", "eicu")]
        for a, b in pairs:
            i, u = bydb[a] & bydb[b], bydb[a] | bydb[b]
            w.writerow([a, b, len(bydb[a]), len(bydb[b]), len(i), len(u),
                        round(len(i) / len(u), 4) if u else 0])

    return {
        "triples_parsed": len(triples), "artifacts_dropped": len(dropped),
        "verified_pairs": len(verified), "parsed_not_in_data": len(set(missing)),
        "base_concepts_total": len(cov),
        "auto_gold_concepts": len(auto), "queue_concepts": len(queue),
        "auto_gold_pairs": sum(1 for v in verified if v["base_concept"] in auto),
        "queue_pairs": sum(1 for v in verified if v["base_concept"] in queue),
        "per_db_concepts": {d: len(s) for d, s in bydb.items()},
    }
