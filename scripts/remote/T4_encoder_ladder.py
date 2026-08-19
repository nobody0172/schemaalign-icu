#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""编码器阶梯 —— 支撑指南 §11.4 消融「LLM 换成普通句向量：是否需要大模型语义表示」。

此前只用了 all-MiniLM-L6-v2 (22M, 6 层蒸馏 BERT)。把它称作「冻结 LLM」站不住,
且没有对照就做不了该条消融。本脚本按参数量与类型建一条阶梯:

  S1 小句向量   all-MiniLM-L6-v2                  22M   mean 池化
  S2 中句向量   BAAI/bge-base-en-v1.5            109M   CLS 池化
  S3 大句向量   BAAI/bge-large-en-v1.5           335M   CLS 池化
  D  生物医学   cambridgeltl/SapBERT-...         110M   CLS 池化   (领域模型对照)
  L1 LLM       gpt2                             124M   **last-token**  (TimeCMA 用的就是它)
  L2 LLM       Qwen/Qwen2.5-1.5B               1.5B   **last-token**

last-token 池化取自 TimeCMA (AAAI'25) `storage/gen_prompt_emb.py` L90:
    last_token_embedding = prompt_embeddings[:, -1, :]
decoder-only 模型只有最后一个 token 能看到完整序列, 均值池化会稀释信息。

C5: 全部 eval() + requires_grad_(False), 无采样, 模板固定并存档。
C1: 渲染文本不含任何主键 (运行时断言)。
"""
import argparse
import csv
import hashlib
import json
import os
import time

import numpy as np
import torch

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
CAT = os.path.join(PROJ, "work", "field_catalog")
GOLD = os.path.join(PROJ, "work", "gold")
OUT = os.path.join(PROJ, "outputs", "T4_ladder")
os.makedirs(OUT, exist_ok=True)

LADDER = {
    "minilm":  ("sentence-transformers/all-MiniLM-L6-v2", "mean", False),
    "bge_base": ("BAAI/bge-base-en-v1.5", "cls", False),
    "bge_large": ("BAAI/bge-large-en-v1.5", "cls", False),
    "sapbert": ("cambridgeltl/SapBERT-from-PubMedBERT-fulltext", "cls", False),
    "gpt2":    ("gpt2", "last", True),
    "qwen15":  ("Qwen/Qwen2.5-1.5B", "last", True),
}

TPL_NAME = "{label}"
TPL_CARD = ("clinical field: {label} | abbreviation: {abbrev} | source table: {table}"
            " | category: {category} | data type: {dtype} | unit: {unit}"
            " | typical range: p01 {p01}, median {p50}, p99 {p99}"
            " | observations per stay: {obs} | missing rate: {miss}")
FORBIDDEN = ("itemid", "labid", "row_id", "subject_id", "hadm_id", "stay_id")
CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}


def render(r, tmpl):
    t = tmpl.format(
        label=(r.get("label") or r.get("field_key") or "unknown").strip() or "unknown",
        abbrev=(r.get("abbreviation") or "none").strip() or "none",
        table=(r.get("src_table") or "unknown").split(".")[-1],
        category=(r.get("dict_category") or "unspecified").strip() or "unspecified",
        dtype=r.get("dtype_inferred") or "unknown",
        unit=(r.get("unit_observed") or "not recorded").strip() or "not recorded",
        p01=r.get("p01") or "na", p50=r.get("p50") or "na", p99=r.get("p99") or "na",
        obs=r.get("obs_per_key") or "na", miss=r.get("missing_rate") or "na")
    low = t.lower()
    for f in FORBIDDEN:
        assert f not in low, "C1 违规: %s -> %s" % (f, t[:100])
    return t


def pool(h, mask, how):
    if how == "cls":
        return h[:, 0, :]
    if how == "last":
        # decoder-only: 取每条序列**最后一个非 padding token** (TimeCMA 的做法)
        idx = mask.sum(1) - 1
        return h[torch.arange(h.size(0), device=h.device), idx]
    m = mask.unsqueeze(-1).float()
    return (h * m).sum(1) / m.sum(1).clamp(min=1)


def encode(name, texts, batch, max_len, dev, gpu_frac):
    from transformers import AutoModel, AutoTokenizer
    path, how, is_llm = LADDER[name]
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    if is_llm:
        tok.padding_side = "left" if how == "last" else "right"
    dt = torch.float16 if (is_llm and dev == "cuda") else torch.float32
    mdl = AutoModel.from_pretrained(path, trust_remote_code=True,
                                    torch_dtype=dt).to(dev).eval()
    for p in mdl.parameters():
        p.requires_grad_(False)
    n_par = sum(p.numel() for p in mdl.parameters())
    outs = []
    for i in range(0, len(texts), batch):
        b = tok(texts[i:i + batch], padding=True, truncation=True,
                max_length=max_len, return_tensors="pt").to(dev)
        with torch.no_grad():
            h = mdl(**b).last_hidden_state
        # left padding 时最后一个 token 就是序列末尾
        if is_llm and how == "last":
            v = h[:, -1, :]
        else:
            v = pool(h, b["attention_mask"], how)
        outs.append(v.float().cpu().numpy().astype("float16"))
    del mdl
    if dev == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(outs, 0), n_par, how


def main(a):
    dev = "cuda" if torch.cuda.is_available() and not a.cpu else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(a.gpu_frac, 0)
    manifest = json.load(open(os.path.join(OUT, "_manifest.json"))) \
        if os.path.exists(os.path.join(OUT, "_manifest.json")) else {"models": {}}

    fields = {db: list(csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")))
              for db, fn in CATF.items()}
    cc = list(csv.DictReader(open(os.path.join(PROJ, "outputs", "T4_embed",
                                              "conceptcard_keys.csv"),
                                  newline="", encoding="utf-8")))
    concepts = [r["base_concept"] for r in csv.DictReader(
        open(os.path.join(GOLD, "concepts.csv"), newline="", encoding="utf-8"))]

    for name in (a.only.split(",") if a.only else list(LADDER)):
        if name in manifest["models"] and not a.force:
            print("[skip] %s" % name, flush=True); continue
        t0 = time.time()
        try:
            for db, rows in fields.items():
                for kind, tmpl in (("name", TPL_NAME), ("card", TPL_CARD)):
                    texts = [render(r, tmpl) for r in rows]
                    E, npar, how = encode(name, texts, a.batch, a.max_len, dev, a.gpu_frac)
                    np.save(os.path.join(OUT, "%s_%s_%s.npy" % (name, db, kind)), E)
                    if kind == "name":
                        with open(os.path.join(OUT, "%s_keys.csv" % db), "w",
                                  newline="", encoding="utf-8") as f:
                            w = csv.writer(f); w.writerow(["field_key"])
                            w.writerows([[r["field_key"]] for r in rows])
            # 概念侧: 概念名 与 ConceptCard 两种, 与字段侧的 name/card 一一对应
            Ec, npar, how = encode(name, [c.replace("_", " ") for c in concepts],
                                   a.batch, a.max_len, dev, a.gpu_frac)
            np.save(os.path.join(OUT, "%s_concept.npy" % name), Ec)
            Ecc, _, _ = encode(name, [r["text"] for r in cc], a.batch, a.max_len, dev, a.gpu_frac)
            np.save(os.path.join(OUT, "%s_conceptcard.npy" % name), Ecc)
            manifest["models"][name] = {
                "path": LADDER[name][0], "pooling": how, "params_M": round(npar / 1e6, 1),
                "dim": int(Ec.shape[1]), "seconds": round(time.time() - t0, 1)}
            print("[ok] %-10s %-42s %7.1fM  %-4s dim=%d  %6.1fs"
                  % (name, LADDER[name][0], npar / 1e6, how, Ec.shape[1],
                     time.time() - t0), flush=True)
        except Exception as e:
            print("[ERR] %-10s %s" % (name, str(e)[:220]), flush=True)
        manifest["template_card"] = TPL_CARD
        manifest["template_sha256"] = hashlib.sha256(
            (TPL_NAME + "||" + TPL_CARD).encode()).hexdigest()[:16]
        json.dump(manifest, open(os.path.join(OUT, "_manifest.json"), "w"),
                  indent=2, ensure_ascii=False)
    print("\n[ladder] 完成 %d 个模型" % len(manifest["models"]), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="")
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--max-len", type=int, default=64)
    p.add_argument("--gpu-frac", type=float, default=0.33)
    p.add_argument("--force", action="store_true")
    p.add_argument("--cpu", action="store_true")
    main(p.parse_args())
