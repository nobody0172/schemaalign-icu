#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T4 · Name-embedding 基线 + 字段卡片嵌入缓存 (执行文档 §5 T4 / T5 第 1 步)。

两件事一次做完:
  ① 基线 3「Name embedding」: **只编码 raw_name**, 不用单位/表/统计。
  ② T5 的前置: 把完整 FieldCard 文本的 token 级隐状态**离线缓存**, 后续训练直接读缓存,
     冻结编码器只前向一次 (C5)。

C1: FieldCard 与 name 文本都**绝不含 itemid / labid / 任何数字型主键**, 只用字典 label。
C5: 编码器 eval() + requires_grad_(False), 模板固定并存档, 无采样 (确定性前向)。

资源: 与 RewardProg-ICU 共存, 显存上限 8 GiB (见 src/sa_guard.sh)。
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
OUT = os.path.join(PROJ, "outputs", "T4_embed")
os.makedirs(OUT, exist_ok=True)

# ── 固定模板, 存档进论文附录 (C5) ─────────────────────────────────────────
TEMPLATE_NAME = "{label}"
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
FORBIDDEN = ("itemid", "labid", "row_id", "subject_id", "hadm_id", "stay_id")


def render(r, tmpl):
    lab = (r.get("label") or r["field_key"]).strip()
    txt = tmpl.format(
        label=lab or "unknown",
        abbrev=(r.get("abbreviation") or "none").strip() or "none",
        table=(r.get("src_table") or "unknown").split(".")[-1],
        category=(r.get("dict_category") or "unspecified").strip() or "unspecified",
        dtype=r.get("dtype_inferred") or "unknown",
        unit=(r.get("unit_observed") or "not recorded").strip() or "not recorded",
        p01=r.get("p01") or "na", p50=r.get("p50") or "na", p99=r.get("p99") or "na",
        obs=r.get("obs_per_key") or "na", miss=r.get("missing_rate") or "na")
    low = txt.lower()
    for f in FORBIDDEN:                      # C1 运行时断言
        assert f not in low, "C1 违规: 模板渲染出现 %s -> %s" % (f, txt[:120])
    return txt


def main(a):
    from transformers import AutoModel, AutoTokenizer
    dev = "cuda" if (torch.cuda.is_available() and not a.cpu) else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(a.gpu_frac, 0)
    tok = AutoTokenizer.from_pretrained(a.model)
    mdl = AutoModel.from_pretrained(a.model).to(dev).eval()
    for p in mdl.parameters():
        p.requires_grad_(False)              # C5
    print("[T4] model=%s dev=%s dim=%d" % (a.model, dev, mdl.config.hidden_size), flush=True)

    manifest = {"model": a.model, "device": dev, "max_len": a.max_len,
                "template_name": TEMPLATE_NAME, "template_card": TEMPLATE_CARD,
                "deterministic": True, "grad": False, "files": {}}
    for db, fn in (("mimic-iv", "field_catalog_m4.csv"),
                   ("mimic-iii", "field_catalog_m3cv.csv"),
                   ("eicu", "field_catalog_eicu.csv")):
        rows = list(csv.DictReader(open(os.path.join(CAT, fn), newline="", encoding="utf-8")))
        rows = [r for r in rows if float(r.get("coverage") or 0) >= a.min_cov]
        for kind, tmpl in (("name", TEMPLATE_NAME), ("card", TEMPLATE_CARD)):
            texts = [render(r, tmpl) for r in rows]
            t0 = time.time()
            pooled, seqs = [], []
            for i in range(0, len(texts), a.batch):
                b = tok(texts[i:i + a.batch], padding="max_length", truncation=True,
                        max_length=a.max_len, return_tensors="pt").to(dev)
                with torch.no_grad():
                    h = mdl(**b).last_hidden_state            # (B, L, D)
                m = b["attention_mask"].unsqueeze(-1).float()
                pooled.append(((h * m).sum(1) / m.sum(1).clamp(min=1)).cpu().numpy().astype("float16"))
                if kind == "card":
                    seqs.append(h.cpu().numpy().astype("float16"))
            P = np.concatenate(pooled, 0)
            np.save(os.path.join(OUT, "%s_%s_pooled.npy" % (db, kind)), P)
            if kind == "card":
                np.save(os.path.join(OUT, "%s_card_seq.npy" % db), np.concatenate(seqs, 0))
            with open(os.path.join(OUT, "%s_%s_keys.csv" % (db, kind)), "w",
                      newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["field_key", "text"])
                w.writerows(zip([r["field_key"] for r in rows], texts))
            manifest["files"]["%s_%s" % (db, kind)] = {
                "n": len(rows), "dim": int(P.shape[1]), "seconds": round(time.time() - t0, 1)}
            print("[ok] %-10s %-5s %5d 字段 %6.1fs -> %s" %
                  (db, kind, len(rows), time.time() - t0, P.shape), flush=True)
    manifest["template_sha256"] = hashlib.sha256(
        (TEMPLATE_NAME + "||" + TEMPLATE_CARD).encode()).hexdigest()[:16]
    json.dump(manifest, open(os.path.join(OUT, "_manifest.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\n[T4] 完成, 模板 sha256=%s" % manifest["template_sha256"], flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--max-len", type=int, default=64)
    ap.add_argument("--min-cov", type=float, default=0.0)
    ap.add_argument("--gpu-frac", type=float, default=0.33)
    ap.add_argument("--cpu", action="store_true")
    main(ap.parse_args())
