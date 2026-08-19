# -*- coding: utf-8 -*-
"""T4 · 评测指标 (执行文档 §5 T4 验收要求的六项)。

Recall@K / Precision / Recall / F1 / Unit-Violation-Rate / Coverage / Open-set AUROC-AUPRC
"""
import collections

from ..gates.rules import FieldSpec, gate_all

__all__ = ["evaluate"]


def _auc(scores, labels):
    """AUROC, 无 sklearn 依赖 (rank 法, 处理并列)。labels: 1=正 0=负。"""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    ranks, i = [0.0] * n, 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    npos = sum(l for _, l in pairs)
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    s = sum(r for r, (_, l) in zip(ranks, pairs) if l == 1)
    return (s - npos * (npos + 1) / 2.0) / (npos * nneg)


def _ap(scores, labels):
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    tp = 0; s = 0.0
    npos = sum(labels)
    if npos == 0:
        return float("nan")
    for rank, i in enumerate(order, 1):
        if labels[i] == 1:
            tp += 1
            s += tp / rank
    return s / npos


def _spec(row, key):
    return FieldSpec(db=None, field_key=key,
                     raw_name=(row.get("label") or key).split("|")[-1],
                     src_table=row["src_table"],
                     unit_observed=row["unit_observed"] or None,
                     dtype_inferred=row["dtype_inferred"],
                     p01=row["p01"], p50=row["p50"], p99=row["p99"],
                     dtype_declared=bool((row.get("param_type") or "").strip()),
                     specimen=row.get("specimen") or None)


def evaluate(evalset, predictions, concept_repr=None, ks=(1, 5, 10), conf=None):
    """
    predictions: {field_key: [概念排序列表]}；空列表 = 判为 UNKNOWN
    concept_repr: {concept: FieldSpec 代表} —— 用于算 Unit-Violation-Rate；None 则跳过
    conf: {field_key: float} 开放集置信度 (通常取 max_c S(j,c))。

    ⚠️ conf=None 时退化为用**二值预测**当分数, 这样算出的 Open-set AUROC 只反映
       某一个阈值下的取舍, 不是真正的排序能力。论文报告的开放集指标必须传 conf。
    """
    pos = [it for it in evalset.items if it["gold"] is not None]
    rec = {}
    for k in ks:
        hit = sum(1 for it in pos if it["gold"] in predictions.get(it["field_key"], [])[:k])
        rec["Recall@%d" % k] = 100.0 * hit / len(pos) if pos else float("nan")

    # top-1 判定下的 P/R/F1（UNKNOWN 不算预测）
    tp = fp = fn = 0
    for it in evalset.items:
        p = predictions.get(it["field_key"], [])
        top = p[0] if p else None
        if it["gold"] is None:
            if top is not None:
                fp += 1                      # 应判 UNKNOWN 却强行匹配
        else:
            if top is None:
                fn += 1
            elif top == it["gold"]:
                tp += 1
            else:
                fp += 1; fn += 1
    P = 100.0 * tp / (tp + fp) if tp + fp else 0.0
    R = 100.0 * tp / (tp + fn) if tp + fn else 0.0
    F1 = 2 * P * R / (P + R) if P + R else 0.0

    n_pred = sum(1 for it in evalset.items if predictions.get(it["field_key"]))
    cov = 100.0 * n_pred / len(evalset.items) if evalset.items else 0.0

    # Unit violation rate: 在做出的 top-1 匹配里, V_unit == 1 的比例
    uv = float("nan")
    if concept_repr:
        viol = tot = 0
        for it in evalset.items:
            p = predictions.get(it["field_key"], [])
            if not p or p[0] not in concept_repr:
                continue
            g = gate_all(_spec(it["row"], it["field_key"]), concept_repr[p[0]], concept_mode=True)
            tot += 1; viol += 1 if g.v_unit == 1 else 0
        uv = 100.0 * viol / tot if tot else float("nan")

    # 开放集: 正类 = 可匹配字段。分数优先用 max_c S(j,c) 的置信度
    if conf is not None:
        sc = [float(conf.get(it["field_key"], -1e9)) for it in evalset.items]
    else:
        sc = [1.0 if predictions.get(it["field_key"]) else 0.0 for it in evalset.items]
    lb = [1 if it["gold"] is not None else 0 for it in evalset.items]
    out = dict(rec)
    out.update({"Precision": P, "Recall": R, "F1": F1, "Coverage": cov,
                "UnitViolRate": uv,
                "OpenSet_AUROC": 100.0 * _auc(sc, lb), "OpenSet_AUPRC": 100.0 * _ap(sc, lb),
                "n_fields": len(evalset.items), "n_positive": len(pos),
                "n_unknown": len(evalset.items) - len(pos)})
    return out
