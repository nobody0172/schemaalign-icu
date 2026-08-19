# -*- coding: utf-8 -*-
"""T4 · 非 LLM 基线 (执行文档 §5 T4)。

B1 Exact / normalized name : 归一后字段名与概念名精确匹配。
                             命中即 rank-1; 无命中 -> UNKNOWN。
                             因此 R@1 = R@5 = R@10 (精确匹配无排序), 如实报告。
B2 Ontology only           : 仅依赖 LOINC。字段 -> LOINC -> 概念。
                             无 LOINC 的字段只能输出 UNKNOWN, **覆盖率如实报告**。
                             MIMIC-IV 侧的 LOINC 由 bridge_loinc_m3_to_m4 回填 (证据台账 E3)。
"""
import csv
import os

from .evalset import normalize_name

__all__ = ["exact_name_baseline", "ontology_baseline", "load_loinc_maps",
           "embedding_baseline", "load_embeddings"]


def exact_name_baseline(evalset):
    """返回 {field_key: [概念, ...] 排序列表}。无命中返回 []。"""
    idx = {}
    for c in evalset.concepts:
        idx.setdefault(normalize_name(c.replace("_", " ")), []).append(c)
    out = {}
    for it in evalset.items:
        out[it["field_key"]] = list(idx.get(normalize_name(it["raw_name"]), []))
    return out


def load_loinc_maps(raw_catalog_dir):
    """
    返回 (itemid -> loinc)。
    MIMIC-III D_LABITEMS 自带 LOINC; MIMIC-IV v3.1 已删该列, 由 680 项 itemid 桥接回填。
    """
    R = lambda n: os.path.join(raw_catalog_dir, "01_field_catalog", n)
    m3 = {r["ITEMID"]: (r["LOINC_CODE"] or "").strip()
          for r in csv.DictReader(open(R("m3_d_labitems.csv"), encoding="utf-8"))}
    m3 = {k: v for k, v in m3.items() if v}
    m4 = {}
    p = R("bridge_loinc_m3_to_m4.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            code = ""
            for key in ("m3_loinc", "loinc_code", "LOINC_CODE"):
                if r.get(key):
                    code = r[key].strip(); break
            iid = r.get("itemid") or r.get("ITEMID")
            if iid and code:
                m4[iid] = code
    return {"mimic-iii": m3, "mimic-iv": m4, "eicu": {}}


def ontology_baseline(evalset, loinc_by_db, concept_loinc):
    """
    concept_loinc: {loinc_code: base_concept} —— 由 gold 中带 LOINC 的字段投票得到,
                   **只用 MIMIC-IV 训练侧的 gold**, 不看目标域 gold (约束 C3)。
    """
    m = loinc_by_db.get(evalset.db, {})
    out = {}
    for it in evalset.items:
        code = m.get(it["field_key"], "")
        c = concept_loinc.get(code) if code else None
        out[it["field_key"]] = [c] if c else []
    return out


def build_concept_loinc(gold_dir, raw_catalog_dir):
    """从 **MIMIC-IV 侧** gold + LOINC 桥接建 loinc -> concept 表 (C3: 不看目标域 gold)。"""
    maps = load_loinc_maps(raw_catalog_dir)
    m4 = maps["mimic-iv"]
    vote = {}
    for r in csv.DictReader(open(os.path.join(gold_dir, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv":
            continue
        code = m4.get(r["field_key"])
        if code:
            vote.setdefault(code, {}).setdefault(r["base_concept"], 0)
            vote[code][r["base_concept"]] += 1
    return {k: max(v, key=v.get) for k, v in vote.items()}, maps


# ── B3: Name embedding ───────────────────────────────────────────────────
def load_embeddings(embed_dir, db, kind="name"):
    """
    返回 ({field_key: 向量}, 概念名列表, 概念矩阵)。冻结编码器的离线缓存 (C5)。

    ⚠️ 概念侧必须与字段侧落在**同一文本空间**:
       kind='name' -> 概念用 concept_pooled (概念名短词)
       kind='card' -> 概念用 conceptcard_pooled (同一 TEMPLATE_CARD 渲染)
    否则余弦相似度被文本长度/格式差异主导, 得到虚假低分。
    """
    import csv as _csv
    import numpy as np
    E = np.load(os.path.join(embed_dir, "%s_%s_pooled.npy" % (db, kind))).astype("float32")
    keys = [r["field_key"] for r in _csv.DictReader(
        open(os.path.join(embed_dir, "%s_%s_keys.csv" % (db, "name")),
             newline="", encoding="utf-8"))]
    cfile, kfile = ("conceptcard_pooled.npy", "conceptcard_keys.csv") if kind == "card" \
        else ("concept_pooled.npy", "concept_keys.csv")
    C = np.load(os.path.join(embed_dir, cfile)).astype("float32")
    cnames = [r["base_concept"] for r in _csv.DictReader(
        open(os.path.join(embed_dir, kfile), newline="", encoding="utf-8"))]
    return dict(zip(keys, E)), cnames, C


def embedding_baseline(evalset, embed_dir, kind="name", topk=10, theta=None):
    """
    只编码 raw_name (kind='name') 或完整 FieldCard (kind='card'), 余弦相似度排序。
    theta: 开放集阈值; None 表示不判 UNKNOWN (纯闭集排序)。
    """
    import numpy as np
    emb, cnames, C = load_embeddings(embed_dir, evalset.db, kind)
    Cn = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    out = {}
    for it in evalset.items:
        v = emb.get(it["field_key"])
        if v is None:
            out[it["field_key"]] = []
            continue
        vn = v / (np.linalg.norm(v) + 1e-9)
        s = Cn @ vn
        idx = np.argsort(-s)[:topk]
        if theta is not None and float(s[idx[0]]) < theta:
            out[it["field_key"]] = []
        else:
            out[it["field_key"]] = [cnames[i] for i in idx]
    return out
