# -*- coding: utf-8 -*-
"""T5b · 用训练好的 facet 表示做匹配 (SAF 式 7 + 确定性门控 + 开放集)。

    S_sem(j,c) = cos(g_j, g_c) + Σ_{k=1..K} cos(facet_k(j), facet_k(c))
    S(j,c)     = S_sem − λ1·V_unit − λ2·V_type − λ3·V_prov  (+ γ·S_stat)
    硬拒 / θ_open 同 T5a。
"""
import csv
import os

import numpy as np

from ..gates.rules import gate_all
from .gated import _spec, _stat_sim

__all__ = ["load_facets", "facet_predict"]


def load_facets(t5b_dir, db, tag="K10_l0.20"):
    R = np.load(os.path.join(t5b_dir, "repr_%s_%s.npy" % (db, tag))).astype("float32")
    keys = [r["field_key"] for r in csv.DictReader(
        open(os.path.join(t5b_dir, "repr_%s_keys.csv" % db), newline="", encoding="utf-8"))]
    P = np.load(os.path.join(t5b_dir, "proto_%s.npy" % tag)).astype("float32")
    return {k: R[i] for i, k in enumerate(keys)}, P


def facet_predict(evalset, t5b_dir, concept_names, concept_reps=None, tag="K10_l0.20",
                  topk=10, gamma=0.0, lam=(1.0, 1.0, 0.5), theta=None,
                  use_gate=True, return_scores=False):
    F, P = load_facets(t5b_dir, evalset.db, tag)
    Pn = P / (np.linalg.norm(P, axis=-1, keepdims=True) + 1e-9)   # (C, 1+K, D)
    out, raw = {}, {}
    for it in evalset.items:
        v = F.get(it["field_key"])
        if v is None:
            out[it["field_key"]] = []
            continue
        vn = v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)   # (1+K, D)
        sem = np.einsum("kd,ckd->c", vn, Pn)      # 逐切片余弦之和, 含 global
        cand = np.argsort(-sem)[:topk]
        fs = _spec(it["row"], it["field_key"])
        scored = []
        for i in cand:
            c = concept_names[i]
            s = float(sem[i])
            rep = (concept_reps or {}).get(c)
            if use_gate and rep is not None:
                g = gate_all(fs, rep, concept_mode=True)
                if g.hard_reject:
                    continue
                s = (s + gamma * _stat_sim(fs, rep)
                     - lam[0] * g.v_unit - lam[1] * g.v_type - lam[2] * g.v_prov)
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        raw[it["field_key"]] = scored
        out[it["field_key"]] = ([c for _, c in scored]
                                if scored and (theta is None or scored[0][0] >= theta) else [])
    return (out, raw) if return_scores else out
