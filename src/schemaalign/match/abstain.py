# -*- coding: utf-8 -*-
"""本文方法：把确定性相容性检查用作**弃权证据**（而非重排信号）。

E34 证明：把检查当重排器叠加在强 LLM 上是负收益（R@1 −2.7~−8.1），
因为强 LLM 本身单位冲突率已仅 0.5–0.7%。
E36 证明：把同一批检查当**弃权证据**则显著有益（开放集 AUROC +6.0 / +5.7）。

判据:
    abstain_score(j) = 1 − w · Σ_d V_d(j, ĉ(j))       d ∈ {unit, type, specimen, provenance}
    分数越低越应判 UNKNOWN。若匹配器本身弃权(未给候选), 分数直接为 0。

四个 V_d 全部是确定性、可打印的规则 (C6)，取值 {0, 0.5, 1}。
"""
import numpy as np

from ..gates.rules import gate_all, v_method

__all__ = ["abstain_scores", "DIMS"]

DIMS = ("unit", "type", "specimen", "provenance", "method")


def abstain_scores(items, predictions, concept_reps, spec_fn, w=0.2, dims=DIMS,
                   base_conf=None):
    """
    items         : evalset.items
    predictions   : {field_key: [概念排序]}；空 = 匹配器自身弃权
    concept_reps  : {concept: FieldSpec}
    spec_fn       : row, key -> FieldSpec
    w             : 每单位违规的扣分权重
    dims          : 参与的检查维度（消融用）
    base_conf     : {field_key: float} 匹配器自身置信度；None 则用 1.0
    返回 {field_key: 弃权分数}，越高越像「可映射」
    """
    out = {}
    for it in items:
        k = it["field_key"]
        p = predictions.get(k, [])
        if not p:
            out[k] = 0.0
            continue
        rep = concept_reps.get(p[0])
        b = 1.0 if base_conf is None else float(base_conf.get(k, 1.0))
        if rep is None:
            out[k] = 0.6 * b
            continue
        sp_ = spec_fn(it["row"], k)
        g = gate_all(sp_, rep, concept_mode=True)
        v = {"unit": g.v_unit, "type": g.v_type,
             "specimen": g.v_specimen, "provenance": g.v_prov,
             "method": v_method(sp_, rep)[0]}
        pen = sum(v[d] for d in dims)
        out[k] = b * (1.0 - w * pen)
    return out


def auroc(scores, labels):
    """labels: 1=可映射(正类), 0=UNKNOWN。无 sklearn 依赖。"""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    ranks, i = [0.0] * n, 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for t in range(i, j + 1):
            ranks[t] = r
        i = j + 1
    npos = sum(l for _, l in pairs)
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    s = sum(r for r, (_, l) in zip(ranks, pairs) if l == 1)
    return (s - npos * (npos + 1) / 2.0) / (npos * nneg)


def bootstrap_ci(scores, labels, n_boot=1000, seed=0):
    """开放集 AUROC 的 95% bootstrap 置信区间（论文主表需要）。"""
    rng = np.random.default_rng(seed)
    s, l = np.asarray(scores), np.asarray(labels)
    n = len(s)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        if 0 < l[idx].sum() < n:
            vals.append(auroc(s[idx].tolist(), l[idx].tolist()))
    if not vals:
        return (float("nan"), float("nan"))
    return tuple(np.percentile(vals, [2.5, 97.5]))
