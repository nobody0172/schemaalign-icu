# -*- coding: utf-8 -*-
"""T5a · 语义召回 + 确定性门控 (指南 §2.1 的打分式, 不含可学习 facet)。

    S(j,c) = S_sem(j,c) + β·S_onto(j,c) + γ·S_stat(j,c)
             − λ1·V_unit − λ2·V_type − λ3·V_prov
    硬拒:  V_unit=1 或 V_type=1 (或 V_prov=1, 取决于 hard_reject_prov) -> S := −∞
    开放集: max_c S(j,c) < θ_open -> UNKNOWN

**这一步不训练任何模型**: S_sem 来自冻结编码器的离线缓存, 门控是 T3 的确定性规则。
它单独检验论文核心主张「语义负责召回、确定性检查负责接受」, 也是 T5b 的对照基线。

C4: θ_open **只能在 MIMIC-IV 验证分割上标定**, 不得在目标域上选。
"""
import numpy as np

from ..gates.rules import FieldSpec, gate_all
from .baselines import load_embeddings

__all__ = ["gated_predict", "calibrate_theta"]


def _spec(row, key):
    return FieldSpec(db=None, field_key=key,
                     raw_name=(row.get("label") or key).split("|")[-1],
                     src_table=row["src_table"],
                     unit_observed=row["unit_observed"] or None,
                     dtype_inferred=row["dtype_inferred"],
                     p01=row["p01"], p50=row["p50"], p99=row["p99"],
                     dtype_declared=bool((row.get("param_type") or "").strip()),
                     specimen=row.get("specimen") or None)


def _stat_sim(a, b):
    """S_stat: 值域重叠程度, 用 log 尺度上的中位数距离, 映射到 [0,1]。缺失返回 0.5 (中性)。"""
    try:
        x, y = float(a.p50), float(b.p50)
    except (TypeError, ValueError):
        return 0.5
    if x <= 0 or y <= 0:
        return 0.5 if abs(x - y) > max(abs(x), abs(y), 1e-6) else 1.0
    d = abs(np.log10(x) - np.log10(y))
    return float(np.exp(-d))                 # 同量级 -> 接近 1, 差一个数量级 -> 0.1


def gated_predict(evalset, embed_dir, concept_reps, kind="card", topk=10,
                  beta=0.0, gamma=0.3, lam=(1.0, 1.0, 0.5), theta=None,
                  hard_reject_prov=True, onto=None, return_scores=False):
    """
    concept_reps: {concept: FieldSpec}  概念代表 (源域 gold 聚合), 供门控使用
    onto: {(field_key, concept): 0/1} 本体一致性, None 则 β 项为 0
    返回 {field_key: [概念排序]}；空 = UNKNOWN
    """
    emb, cnames, C = load_embeddings(embed_dir, evalset.db, kind)
    Cn = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    out, raw = {}, {}
    for it in evalset.items:
        v = emb.get(it["field_key"])
        if v is None:
            out[it["field_key"]] = []
            continue
        vn = v / (np.linalg.norm(v) + 1e-9)
        sem = Cn @ vn
        cand = np.argsort(-sem)[:topk]       # 语义只负责**召回**
        fs = _spec(it["row"], it["field_key"])
        scored = []
        for i in cand:
            c = cnames[i]
            rep = concept_reps.get(c)
            s = float(sem[i])
            if rep is not None:
                g = gate_all(fs, rep, hard_reject_prov=hard_reject_prov, concept_mode=True)
                if g.hard_reject:            # 确定性检查负责**接受**
                    continue
                s = (s
                     + beta * (1.0 if onto and onto.get((it["field_key"], c)) else 0.0)
                     + gamma * _stat_sim(fs, rep)
                     - lam[0] * g.v_unit - lam[1] * g.v_type - lam[2] * g.v_prov)
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        raw[it["field_key"]] = scored
        if not scored or (theta is not None and scored[0][0] < theta):
            out[it["field_key"]] = []
        else:
            out[it["field_key"]] = [c for _, c in scored]
    return (out, raw) if return_scores else out


def calibrate_theta(evalset_val, embed_dir, concept_reps, grid=None, **kw):
    """
    C4: 在 **MIMIC-IV 验证分割** 上选 θ_open, 目标 = 开放集 F1 最大。
    返回 (theta*, 逐点记录)。
    """
    from .metrics import evaluate
    if grid is None:
        grid = [round(x, 3) for x in np.arange(-0.60, 1.01, 0.02)]
    _, raw = gated_predict(evalset_val, embed_dir, concept_reps,
                           theta=None, return_scores=True, **kw)
    rec, best = [], (None, -1)
    for th in grid:
        pred = {k: ([c for _, c in v] if v and v[0][0] >= th else []) for k, v in raw.items()}
        m = evaluate(evalset_val, pred, concept_reps)
        rec.append({"theta": th, "F1": m["F1"], "Recall@1": m["Recall@1"],
                    "Precision": m["Precision"], "Coverage": m["Coverage"],
                    "OpenSet_AUROC": m["OpenSet_AUROC"]})
        if m["F1"] > best[1]:
            best = (th, m["F1"])
    return best[0], rec
