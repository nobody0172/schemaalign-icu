#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T5b · 双视图 + 共享 facet 聚合 + CMPM/CMPC + diversity (执行文档 §5 T5)。

结构完全对齐 SAF (docs/plans/SAF二次开发方案_v1.md):
    image(ViT)  -> lexical view  : FieldCard 文本 -> 冻结编码器 token 级隐状态 (离线缓存)
    text(BERT)  -> evidence view : 9 个离散属性 token -> 可学习嵌入表
    shared Block(K heads)        -> 共享 facet 聚合器 (参数共享不变)
    person id                    -> canonical concept id
    L = L_global + L_facet + λ·L_div ; Sim = cos(g) + Σ_k cos(facet_k)

约束:
  C1 证据视图无任何主键; 词法视图用 label 渲染的卡片
  C3 **只用 MIMIC-IV 侧 gold 训练**; CareVue/eICU 的 gold 仅用于评测
  C4 分桶边界与 θ_open 只在 MIMIC-IV 训练/验证分割上定
  C5 冻结编码器不参与训练, 只读缓存
"""
import argparse
import csv
import json
import os
import sys
import time
import zlib

import numpy as np
import torch
import torch.nn as nn

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
sys.path.insert(0, os.path.join(PROJ, "src"))
W = os.path.join(PROJ, "work")
EMB = os.path.join(PROJ, "outputs", "T4_embed")
OUT = os.path.join(PROJ, "outputs", "T5b")
os.makedirs(OUT, exist_ok=True)

from schemaalign.encoders.evidence import FIELDS, EvidenceVocab      # noqa: E402
from schemaalign.facets.model import SchemaAlignConfig, SchemaAlignModel  # noqa: E402
from schemaalign.losses.saf_losses import SchemaAlignLoss            # noqa: E402

CATF = {"mimic-iv": "field_catalog_m4.csv", "mimic-iii": "field_catalog_m3cv.csv",
        "eicu": "field_catalog_eicu.csv"}


def load_db(db, vocab):
    rows = list(csv.DictReader(open(os.path.join(W, "field_catalog", CATF[db]),
                                    newline="", encoding="utf-8")))
    keys = [r["field_key"] for r in csv.DictReader(
        open(os.path.join(EMB, "%s_name_keys.csv" % db), newline="", encoding="utf-8"))]
    pos = {k: i for i, k in enumerate(keys)}
    seq = np.load(os.path.join(EMB, "%s_card_seq.npy" % db), mmap_mode="r")
    idx, attrs, order = [], [], []
    for r in rows:
        if r["field_key"] not in pos:
            continue
        idx.append(pos[r["field_key"]]); order.append(r["field_key"])
        attrs.append(vocab.transform(r))
    return order, np.asarray(idx), attrs, seq


def _conceptcard_attrs(names, vocab):
    """ConceptCard 的证据属性: 从 **MIMIC-IV 侧 gold 字段** 聚合 (C3/C4)。"""
    cat = {r["field_key"]: r for r in csv.DictReader(
        open(os.path.join(W, "field_catalog", CATF["mimic-iv"]),
             newline="", encoding="utf-8"))}
    agg = {}
    for r in csv.DictReader(open(os.path.join(W, "gold", "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] == "mimic-iv" and r["field_key"] in cat:
            agg.setdefault(r["base_concept"], []).append(cat[r["field_key"]])
    out = []
    for n in names:
        rows = agg.get(n)
        if rows:
            rows = sorted(rows, key=lambda x: -int(x["n_rows"] or 0))
            out.append(vocab.transform(rows[0]))
        else:                                # 无源域证据 -> 全部落到缺失档
            out.append(vocab.transform({}))
    return out


def attr_tensor(attrs, sel, dev):
    return {f: torch.tensor([attrs[i][f] for i in sel], dtype=torch.long, device=dev)
            for f in FIELDS}


def facet_repr(model, seq, idx, attrs, sel, dev, bs=256):
    """两视图融合表示 (N, 1+K, D)。"""
    outs = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(sel), bs):
            s = sel[i:i + bs]
            lex = torch.tensor(np.asarray(seq[idx[s]], dtype=np.float32), device=dev)
            msk = torch.ones(lex.shape[:2], device=dev)
            _, _, _, _, lf, ef = model(lex, msk, attr_tensor(attrs, s, dev))
            outs.append((0.5 * (lf + ef)).cpu())
    return torch.cat(outs, 0)


def main(a):
    dev = "cuda" if torch.cuda.is_available() and not a.cpu else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(a.gpu_frac, 0)
    torch.manual_seed(a.seed); np.random.seed(a.seed)

    vocab = EvidenceVocab.load(os.path.join(W, "gold", "evidence_vocab.json"))
    concepts = [r["base_concept"] for r in csv.DictReader(
        open(os.path.join(W, "gold", "concepts.csv"), newline="", encoding="utf-8"))]
    cid = {c: i for i, c in enumerate(concepts)}

    data = {db: load_db(db, vocab) for db in CATF}
    order, idx, attrs, seq = data["mimic-iv"]
    kpos = {k: i for i, k in enumerate(order)}

    # C3: 只用 MIMIC-IV 侧 gold; C4: 按 field_key 确定性切分
    tr, va = [], []
    for r in csv.DictReader(open(os.path.join(W, "gold", "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or r["field_key"] not in kpos or r["base_concept"] not in cid:
            continue
        b = zlib.crc32(r["field_key"].encode()) % 10
        (tr if b < 7 else va).append((kpos[r["field_key"]], cid[r["base_concept"]]))
    print("[T5b] 训练对 %d / 验证对 %d | 概念 %d | dev=%s"
          % (len(tr), len(va), len(concepts), dev), flush=True)
    if len(tr) < 16:
        sys.exit("训练对太少")

    sizes = vocab.sizes()
    cfg = SchemaAlignConfig(d_frozen=seq.shape[2], D=a.dim, K=a.K,
                            n_bucket=sizes["p01_bucket"], n_unit=sizes["unit_class"],
                            n_dtype=sizes["dtype"], n_prov=sizes["table_provenance"],
                            n_cat=sizes["category"], ev_dropout=a.dropout)
    model = SchemaAlignModel(cfg).to(dev)
    crit = SchemaAlignLoss(cfg.D, len(concepts)).to(dev)
    opt = torch.optim.Adam(list(model.parameters()) + list(crit.parameters()),
                           lr=a.lr, weight_decay=a.wd)

    ti = np.array([x[0] for x in tr]); tl = np.array([x[1] for x in tr])
    best, hist = (1e9, None), []
    for ep in range(1, a.epochs + 1):
        model.train()
        perm = np.random.permutation(len(ti))
        tot = 0.0
        for i in range(0, len(perm), a.batch):
            s = ti[perm[i:i + a.batch]]
            y = torch.tensor(tl[perm[i:i + a.batch]], dtype=torch.long, device=dev)
            if len(s) < 4:
                continue
            lex = torch.tensor(np.asarray(seq[idx[s]], dtype=np.float32), device=dev)
            msk = torch.ones(lex.shape[:2], device=dev)
            lo, eo, _, _, lf, ef = model(lex, msk, attr_tensor(attrs, s, dev))
            cm, cc, loss, _, _, _, _ = crit(lo, eo, lf, ef, y, a.lam_div)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss)
        hist.append(tot)
        if tot < best[0]:
            best = (tot, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()})
        if ep % 10 == 0 or ep == 1:
            print("  ep%3d loss=%.3f" % (ep, tot), flush=True)
    if best[1]:
        model.load_state_dict(best[1])

    # ── 概念原型: A 类中心 (源域训练分割) + B ConceptCard 兜底 (Q7 裁决) ──
    # 实测 MIMIC-IV 侧训练对仅 145 个而概念有 138 个, 平均每概念约 1 个字段,
    # 因此 min_fields 必须取 1; 完全没有源域字段的概念走 ConceptCard 兜底。
    from schemaalign.match.prototypes import build_concept_prototypes
    sel = np.array(sorted({x[0] for x in tr}))
    R = facet_repr(model, seq, idx, attrs, sel, dev)
    lab = torch.tensor([dict((x[0], x[1]) for x in tr)[i] for i in sel], dtype=torch.long)

    # B: ConceptCard 过同一个模型 -> facet 空间的兜底原型
    card = np.load(os.path.join(EMB, "conceptcard_seq.npy"), mmap_mode="r") \
        if os.path.exists(os.path.join(EMB, "conceptcard_seq.npy")) else None
    cc_repr = None
    if card is not None:
        cc_names = [r["base_concept"] for r in csv.DictReader(
            open(os.path.join(EMB, "conceptcard_keys.csv"), newline="", encoding="utf-8"))]
        cc_attr = _conceptcard_attrs(cc_names, vocab)
        cc_idx = np.arange(len(cc_names))
        cc_repr = facet_repr(model, card, cc_idx, cc_attr, cc_idx, dev)
        # 对齐到 concepts 顺序
        pos = {n: i for i, n in enumerate(cc_names)}
        cc_repr = torch.stack([cc_repr[pos[c]] if c in pos
                               else torch.zeros_like(cc_repr[0]) for c in concepts])

    proto, src = build_concept_prototypes(R, lab, len(concepts), cc_repr, a.min_fields)
    print("[T5b] 原型: 类中心 %d, ConceptCard 兜底 %d, 无来源 %d"
          % (int((src == 0).sum()), int((src == 1).sum()), int((src == 2).sum())), flush=True)

    torch.save({"model": model.state_dict(), "proto": proto, "proto_src": src,
                "concepts": concepts, "cfg": vars(cfg), "hist": hist,
                "args": vars(a)}, os.path.join(OUT, "model_K%d_l%.2f.pt" % (a.K, a.lam_div)))

    # 导出三库的 facet 表示, 供本地评测 (含门控与开放集)
    for db in CATF:
        o, ix, at, sq = data[db]
        allsel = np.arange(len(o))
        Rd = facet_repr(model, sq, ix, at, allsel, dev)
        np.save(os.path.join(OUT, "repr_%s_K%d_l%.2f.npy" % (db, a.K, a.lam_div)),
                Rd.numpy().astype("float16"))
        with open(os.path.join(OUT, "repr_%s_keys.csv" % db), "w",
                  newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["field_key"]); w.writerows([[k] for k in o])
    np.save(os.path.join(OUT, "proto_K%d_l%.2f.npy" % (a.K, a.lam_div)),
            proto.numpy().astype("float16"))
    json.dump({"concepts": concepts, "proto_src": src.tolist(),
               "n_train": len(tr), "n_val": len(va), "final_loss": hist[-1],
               "best_loss": best[0]},
              open(os.path.join(OUT, "meta_K%d_l%.2f.json" % (a.K, a.lam_div)), "w"),
              indent=2, ensure_ascii=False)
    print("[T5b] 完成 K=%d λ=%.2f, best_loss=%.3f" % (a.K, a.lam_div, best[0]), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--K", type=int, default=10)
    p.add_argument("--lam-div", type=float, default=0.2)
    p.add_argument("--dim", type=int, default=256)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--wd", type=float, default=4e-5)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--min-fields", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--gpu-frac", type=float, default=0.33)
    p.add_argument("--cpu", action="store_true")
    main(p.parse_args())
