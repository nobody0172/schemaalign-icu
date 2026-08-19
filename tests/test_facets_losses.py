# -*- coding: utf-8 -*-
"""SAF 二次开发模块的回归测试。逐条对应 docs/plans/SAF二次开发方案_v1.md 的核对结论。"""
import os
import sys

import pytest
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from schemaalign.facets.attention import Attention, Block
from schemaalign.facets.model import EVIDENCE_FIELDS, SchemaAlignConfig, SchemaAlignModel
from schemaalign.losses.saf_losses import SchemaAlignLoss, l2norm
from schemaalign.match.prototypes import build_concept_prototypes
from schemaalign.match.retrieval import recall_at_k, s_sem

D, K, B = 256, 6, 8


def _ids(cfg, b=B):
    return {f: torch.randint(0, cfg.vocab(f), (b,)) for f in EVIDENCE_FIELDS}


# ---------- 结构 ----------
def test_block_shapes():
    blk = Block(dim=D, num_heads=K)
    parts, attn = blk(torch.randn(B, 12, D), torch.ones(B, 12))
    assert len(parts) == K and tuple(parts[0].shape) == (B, 12, D)
    assert tuple(attn.shape) == (B, K, 12, 12)


def test_scale_is_dim_not_dim_over_heads():
    """SAF 刻意设计: head_dim = dim, 故 scale = dim^-0.5。"""
    assert Attention(D, num_heads=K).scale == pytest.approx(D ** -0.5)


def test_no_dead_proj_param():
    """SAF 的 Attention.proj 是死参数 (K=10,D=768 时 5.90M), 我们不建。"""
    assert not hasattr(Attention(D, num_heads=K), "proj")


def test_no_residual_by_default():
    """Q8 已裁决: 与 SAF 源码一致, 不加残差。"""
    blk = Block(dim=D, num_heads=K, use_residual=False)
    with torch.no_grad():
        blk.attn.qkv.weight.zero_()
    parts, _ = blk(torch.randn(B, 5, D))
    assert torch.allclose(parts[0], torch.zeros_like(parts[0]))   # 无残差 => 恒零


def test_residual_switch_works():
    blk = Block(dim=D, num_heads=K, use_residual=True)
    with torch.no_grad():
        blk.attn.qkv.weight.zero_()
    x = torch.randn(B, 5, D)
    parts, _ = blk(x)
    assert torch.allclose(parts[0], x, atol=1e-5)                 # 有残差 => 恒等


# ---------- reshape 修正 ----------
def test_fixed_reshape_matches_true_head():
    """修正版第 k 片必须等于第 k 个头的真实注意力输出。"""
    torch.manual_seed(0)
    att = Attention(D, num_heads=K, legacy_reshape=False)
    x = torch.randn(2, 4, D)
    out, attn = att(x)
    qkv = att.qkv(x).reshape(2, 4, 3, K, D).permute(2, 0, 3, 1, 4)
    ref = attn @ qkv[2]                                            # (B,K,N,C)
    for k in range(K):
        assert torch.allclose(out[k], ref[:, k], atol=1e-5)


def test_legacy_reshape_scrambles_heads():
    """复现开关必须真的复现 SAF 的错位行为 (否则开关无意义)。"""
    torch.manual_seed(0)
    x = torch.randn(2, 4, D)
    a_fix = Attention(D, num_heads=K, legacy_reshape=False)
    a_leg = Attention(D, num_heads=K, legacy_reshape=True)
    a_leg.load_state_dict(a_fix.state_dict())
    o_fix, _ = a_fix(x)
    o_leg, _ = a_leg(x)
    assert not torch.allclose(o_fix[0], o_leg[0])                  # 确实不同
    assert torch.allclose(o_fix.flatten().sort().values,
                          o_leg.flatten().sort().values, atol=1e-5)  # 但只是置换


# ---------- 损失 ----------
def test_diversity_zero_on_orthogonal_and_positive_on_identical():
    L = SchemaAlignLoss(D, 80)
    eye = torch.eye(K, D).unsqueeze(0).repeat(4, 1, 1)
    assert L.diversity_loss(eye).item() == pytest.approx(0.0, abs=1e-6)
    same = torch.randn(4, 1, D).repeat(1, K, 1)
    assert L.diversity_loss(same).item() > 0.05


def test_l2norm_no_nan_on_zero_vector():
    """SAF 的 l2norm 无 eps, 零向量会 NaN; 我们必须防住。"""
    assert torch.isfinite(l2norm(torch.zeros(2, 3, D))).all()


def test_loss_backward_and_device_agnostic():
    cfg = SchemaAlignConfig(D=D, K=K)
    m, L = SchemaAlignModel(cfg), SchemaAlignLoss(D, 80)
    lo, eo, _, _, lf, ef = m(torch.randn(B, 17, cfg.d_frozen), torch.ones(B, 17), _ids(cfg))
    _, _, loss, _, _, _, _ = L(lo, eo, lf, ef, torch.randint(0, 80, (B,)), 0.2)
    loss.backward()
    assert torch.isfinite(loss) and m.block.attn.qkv.weight.grad is not None


def test_frozen_lexical_encoder_absent():
    """C5: 模型内不得含任何词法编码器权重, 只吃离线缓存。"""
    names = [n for n, _ in SchemaAlignModel(SchemaAlignConfig(D=D, K=K)).named_parameters()]
    assert not any(("bert" in n.lower() or "encoder" in n.lower()) for n in names)


# ---------- C1 ----------
def test_no_primary_key_in_evidence_view():
    bad = ("itemid", "labid", "item_id", "lab_id", "row_id", "hadm_id", "stay_id")
    assert not any(b in f for f in EVIDENCE_FIELDS for b in bad)


# ---------- 检索 ----------
def test_ssem_equals_saf_accumulation():
    """S_sem 必须逐位等于 SAF compute_topk 的逐切片余弦累加。"""
    torch.manual_seed(0)
    f, p = torch.randn(5, 1 + K, D), torch.randn(7, 1 + K, D)
    ref = torch.zeros(5, 7)
    for i in range(1 + K):
        ref += torch.matmul(f[:, i] / f[:, i].norm(dim=1, keepdim=True),
                            (p[:, i] / p[:, i].norm(dim=1, keepdim=True)).t())
    assert torch.allclose(s_sem(f, p), ref, atol=1e-5)


def test_prototypes_fallback_and_source_flags():
    torch.manual_seed(0)
    N, C = 20, 5
    ids = torch.tensor([0] * 8 + [1] * 6 + [2] * 4 + [3] * 1 + [4] * 1)
    card = torch.randn(C, 1 + K, D)
    proto, src = build_concept_prototypes(torch.randn(N, 1 + K, D), ids, C,
                                          conceptcard_repr=card, min_fields=3)
    assert src.tolist() == [0, 0, 0, 1, 1]                         # 后两个概念走兜底
    assert torch.allclose(proto.norm(dim=-1), torch.ones(C, 1 + K), atol=1e-5)


def test_prototypes_mark_unreachable_without_fallback():
    ids = torch.tensor([0] * 5 + [1] * 1)
    _, src = build_concept_prototypes(torch.randn(6, 1 + K, D), ids, 2, None, min_fields=3)
    assert src.tolist() == [0, 2]                                  # 无兜底 => 标为不可检索


def test_recall_at_k_and_hard_reject():
    s = torch.tensor([[3.0, 1.0, 2.0], [0.5, 4.0, 0.1], [1.0, 0.2, 0.3]])
    assert recall_at_k(s, torch.tensor([0, 1, 0]), ks=(1,))[1] == pytest.approx(100.0)
    assert recall_at_k(s, torch.tensor([2, 0, 1]), ks=(1,))[1] == pytest.approx(0.0)
    # 第 3 行 target=1 排在第 3 位 => top-2 只命中 2/3
    assert recall_at_k(s, torch.tensor([2, 0, 1]), ks=(2,))[2] == pytest.approx(200.0 / 3)
    assert recall_at_k(s, torch.tensor([2, 0, 1]), ks=(3,))[3] == pytest.approx(100.0)
    # 门控硬拒: 把 row0 的正确答案置 -inf, Recall@1 应从 100 掉到 2/3
    s2 = s.clone(); s2[0, 0] = float("-inf")
    assert recall_at_k(s2, torch.tensor([0, 1, 0]), ks=(1,))[1] == pytest.approx(200.0 / 3)
    # UNKNOWN 样本 (ignore_index) 应被跳过而非计为错
    assert recall_at_k(s, torch.tensor([0, -1, -1]), ks=(1,))[1] == pytest.approx(100.0)
    # 形状不一致必须报错, 而不是静默广播
    with pytest.raises(ValueError):
        recall_at_k(s, torch.tensor([0]), ks=(1,))
