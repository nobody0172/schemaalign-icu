# -*- coding: utf-8 -*-
"""S_sem 与 Recall@K。

S_sem 完全照抄 SAF 式 (7) / utils/metric.py compute_topk 的累加方式:
    Sim = cos(global) + sum_{k=1..K} cos(facet_k)
即对 (1+K) 个切片各自 L2 归一后求余弦, **含下标 0 的 global**, 再相加。

相对 SAF compute_topk 的两处修正:
  - 删掉 L339-341 的死代码 (先算了一次 sim_cosine 又被循环覆盖)
  - score 建在与输入同一 device (SAF 硬编码 CPU)
"""
import torch
import torch.nn.functional as F

__all__ = ["s_sem", "recall_at_k"]


def s_sem(field_f, concept_proto):
    """
    field_f       : (N, 1+K, D)
    concept_proto : (C, 1+K, D)
    返回           : (N, C)   —— 逐切片余弦之和
    """
    if field_f.shape[1:] != concept_proto.shape[1:]:
        raise ValueError("切片数/维度不匹配: %s vs %s"
                         % (tuple(field_f.shape), tuple(concept_proto.shape)))
    a = F.normalize(field_f, dim=-1)
    b = F.normalize(concept_proto, dim=-1)
    return torch.einsum("nkd,ckd->nc", a, b)


def recall_at_k(scores, targets, ks=(1, 5, 10), ignore_index=-1):
    """
    scores  : (N, C)   越大越好; 被硬拒的候选应已置为 -inf
    targets : (N,)     金标准概念 id; 等于 ignore_index 的样本被跳过 (如 UNKNOWN)
    返回     : dict {k: 百分比}
    """
    if scores.shape[0] != targets.shape[0]:
        raise ValueError("scores 与 targets 的样本数不一致: %d vs %d"
                         % (scores.shape[0], targets.shape[0]))
    keep = targets != ignore_index
    if keep.sum() == 0:
        return {k: float("nan") for k in ks}
    s, t = scores[keep], targets[keep]
    maxk = min(max(ks), s.shape[1])
    _, idx = s.topk(maxk, dim=1, largest=True, sorted=True)
    hit = idx.eq(t.view(-1, 1))
    return {k: (hit[:, :min(k, maxk)].any(dim=1).float().mean() * 100).item() for k in ks}
