#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ConceptCard —— 让概念侧与字段侧落在**同一个文本空间**。

**为什么必须有**: 若字段侧用完整 FieldCard 长文本、概念侧只用概念名短词,
余弦相似度会被文本格式与长度差异主导, 得到虚假的低分 (实测 R@1 仅 7.3/6.9/0.0)。
这是表征不匹配的假象, 不是 FieldCard 无效。

ConceptCard 的期望属性来自 **MIMIC-IV 训练分割侧的 gold 字段聚合** (C3/C4):
  - 期望单位 = 该概念在 MIMIC-IV 侧 gold 字段的实测单位众数
  - 期望值域 = 行数加权的 p01/p50/p99 中位数
  - 期望来源 = 出现最多的 src_table 族
目标域 (CareVue/eICU) 的 gold **完全不参与**。

这同时是 Q7 裁决里 B 兜底方案的实体: 训练字段 <3 的概念用 ConceptCard 作原型。
"""
import csv
import json
import os
import statistics

import numpy as np
import torch

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
OUT = os.path.join(PROJ, "outputs", "T4_embed")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# 必须与 T4_name_embedding.py 的 TEMPLATE_CARD 逐字一致
TEMPLATE_CARD = (
    "clinical field: {label}"
    " | abbreviation: {abbrev}"
    " | source table: {table}"
    " | category: {category}"
    " | data type: {dtype}"
    " | unit: {unit}"
    " | typical range: p01 {p01}, median {p50}, p99 {p99}"
    " | observations per stay: {obs}"
    " | missing rate: {miss}"
)


def _med(vals):
    v = [float(x) for x in vals if x not in (None, "", "na")]
    return round(statistics.median(v), 4) if v else "na"


def _mode(vals):
    v = [x for x in vals if x]
    return statistics.mode(v) if v else ""


if __name__ == "__main__":
    from transformers import AutoModel, AutoTokenizer
    W = os.path.join(PROJ, "work")
    cat = {r["field_key"]: r for r in csv.DictReader(
        open(os.path.join(W, "field_catalog", "field_catalog_m4.csv"),
             newline="", encoding="utf-8"))}
    concepts = [r["base_concept"] for r in csv.DictReader(
        open(os.path.join(W, "gold", "concepts.csv"), newline="", encoding="utf-8"))]

    agg = {}
    for r in csv.DictReader(open(os.path.join(W, "gold", "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv":            # C3: 只用源域
            continue
        c = cat.get(r["field_key"])
        if not c:
            continue
        agg.setdefault(r["base_concept"], []).append(c)

    texts, meta = [], []
    for name in concepts:
        rows = agg.get(name, [])
        if rows:
            card = TEMPLATE_CARD.format(
                label=name.replace("_", " "),
                abbrev=_mode([r.get("abbreviation") or "" for r in rows]) or "none",
                table=_mode([(r.get("src_table") or "").split(".")[-1] for r in rows]) or "unknown",
                category=_mode([r.get("dict_category") or "" for r in rows]) or "unspecified",
                dtype=_mode([r.get("dtype_inferred") or "" for r in rows]) or "unknown",
                unit=_mode([r.get("unit_observed") or "" for r in rows]) or "not recorded",
                p01=_med([r.get("p01") for r in rows]), p50=_med([r.get("p50") for r in rows]),
                p99=_med([r.get("p99") for r in rows]),
                obs=_med([r.get("obs_per_key") for r in rows]),
                miss=_med([r.get("missing_rate") for r in rows]))
            src = "aggregated_from_mimiciv_gold"
        else:
            # 无源域 gold 的概念: 只能给出名字, 其余槽位标 not recorded (如实)
            card = TEMPLATE_CARD.format(
                label=name.replace("_", " "), abbrev="none", table="unknown",
                category="unspecified", dtype="unknown", unit="not recorded",
                p01="na", p50="na", p99="na", obs="na", miss="na")
            src = "name_only"
        texts.append(card); meta.append((name, src, len(rows)))

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(0.33, 0)
    tok = AutoTokenizer.from_pretrained(MODEL)
    mdl = AutoModel.from_pretrained(MODEL).to(dev).eval()
    for p in mdl.parameters():
        p.requires_grad_(False)
    b = tok(texts, padding="max_length", truncation=True, max_length=64,
            return_tensors="pt").to(dev)
    with torch.no_grad():
        h = mdl(**b).last_hidden_state
    m = b["attention_mask"].unsqueeze(-1).float()
    P = ((h * m).sum(1) / m.sum(1).clamp(min=1)).cpu().numpy().astype("float16")
    np.save(os.path.join(OUT, "conceptcard_pooled.npy"), P)
    with open(os.path.join(OUT, "conceptcard_keys.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["base_concept", "evidence_source", "n_src_fields", "text"])
        for (n, s, k), t in zip(meta, texts):
            w.writerow([n, s, k, t])
    n_agg = sum(1 for _, s, _ in meta if s == "aggregated_from_mimiciv_gold")
    print("[ok] ConceptCard %d 个 (源域聚合 %d, 仅名字 %d) -> %s"
          % (len(meta), n_agg, len(meta) - n_agg, P.shape))
