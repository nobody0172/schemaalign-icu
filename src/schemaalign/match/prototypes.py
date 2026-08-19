# -*- coding: utf-8 -*-
"""概念侧表示 —— 方案 A + B 兜底 (已裁决 Q7)。

SAF 的检索是 text -> image, 两侧都是「同一身份的两个视图」; 我们的检索是
「字段 -> 概念」, 而概念没有天然的两视图。执行文档 §3.1 的对齐表未定义概念侧,
裁决为:

  A (主)   类中心原型: 概念 c 的第 k 个 facet 原型 = MIMIC-IV **训练分割**中所有
           标注为 c 的字段的 facet-k 表示 (两视图融合后) 的 L2 归一化均值。
  B (兜底) ConceptCard: 训练字段数 < min_fields 的概念, 改用其规范卡片
           (规范名 + 期望单位类 + 期望 dtype + 期望来源 + 期望值域) 过同一套
           双视图编码器得到的表示。门控引擎本来就要维护这份「每概念期望属性」表,
           因此 B 的输入几乎零额外人工。

约束:
  C3  只能用 **MIMIC-IV 侧** 的 gold 建原型; CareVue / eICU 侧 gold 仅用于评测。
  C4  统计与原型只在 MIMIC-IV 训练分割上算。
"""
import torch

__all__ = ["build_concept_prototypes"]


def build_concept_prototypes(field_repr, concept_ids, num_concepts,
                             conceptcard_repr=None, min_fields=3):
    """
    field_repr       : (N, 1+K, D)  MIMIC-IV 训练分割字段的两视图融合表示
    concept_ids      : (N,)         每个字段的概念 id, 取值 [0, num_concepts)
    conceptcard_repr : (num_concepts, 1+K, D) 或 None —— 方案 B 的兜底表示
    min_fields       : 少于该字段数的概念改用兜底

    返回 (prototypes (C,1+K,D) 已 L2 归一, source (C,) int8)
         source: 0=类中心(A)  1=ConceptCard 兜底(B)  2=无来源(该概念不可检索)
    """
    if field_repr.dim() != 3:
        raise ValueError("field_repr 应为 (N, 1+K, D), 实为 %s" % (tuple(field_repr.shape),))
    N, S, D = field_repr.shape
    dev, dt = field_repr.device, field_repr.dtype

    counts = torch.zeros(num_concepts, device=dev, dtype=dt)
    counts.index_add_(0, concept_ids, torch.ones(N, device=dev, dtype=dt))
    summed = torch.zeros(num_concepts, S, D, device=dev, dtype=dt)
    summed.index_add_(0, concept_ids, field_repr)

    proto = summed / counts.clamp(min=1).view(-1, 1, 1)
    source = torch.zeros(num_concepts, device=dev, dtype=torch.int8)
    source[counts < min_fields] = 2                      # 先标为「无来源」

    if conceptcard_repr is not None:
        if tuple(conceptcard_repr.shape) != (num_concepts, S, D):
            raise ValueError("conceptcard_repr 形状应为 (%d,%d,%d)" % (num_concepts, S, D))
        need = source == 2
        proto[need] = conceptcard_repr[need].to(dt)
        source[need] = 1                                 # 兜底生效

    proto = proto / (proto.norm(dim=-1, keepdim=True) + 1e-12)
    return proto, source
