#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用同一个冻结编码器编码概念目录, 供 Name-embedding 基线与 T5 的概念原型冷启动使用。

C3: 概念侧文本只用 base_concept 归一名, **不引入任何来自目标库字段名的别名**。
"""
import csv
import json
import os

import numpy as np
import torch

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
OUT = os.path.join(PROJ, "outputs", "T4_embed")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"

if __name__ == "__main__":
    from transformers import AutoModel, AutoTokenizer
    rows = list(csv.DictReader(open(os.path.join(PROJ, "work", "field_catalog", "..",
                                                 "gold", "concepts.csv"),
                                    newline="", encoding="utf-8")))
    names = [r["base_concept"] for r in rows]
    texts = [n.replace("_", " ") for n in names]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(0.33, 0)
    tok = AutoTokenizer.from_pretrained(MODEL)
    mdl = AutoModel.from_pretrained(MODEL).to(dev).eval()
    for p in mdl.parameters():
        p.requires_grad_(False)
    b = tok(texts, padding="max_length", truncation=True, max_length=64, return_tensors="pt").to(dev)
    with torch.no_grad():
        h = mdl(**b).last_hidden_state
    m = b["attention_mask"].unsqueeze(-1).float()
    P = ((h * m).sum(1) / m.sum(1).clamp(min=1)).cpu().numpy().astype("float16")
    np.save(os.path.join(OUT, "concept_pooled.npy"), P)
    with open(os.path.join(OUT, "concept_keys.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["base_concept", "text"]); w.writerows(zip(names, texts))
    print("[ok] 概念 %d 个 -> %s" % (len(names), P.shape))
