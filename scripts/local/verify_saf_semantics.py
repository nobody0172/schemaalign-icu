#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对 refs/SAF 的四条关键语义；docs/plans/SAF二次开发方案_v1.md 中所有「已数值验证」结论由本脚本产出。

用法: python3 scripts/local/verify_saf_semantics.py
"""
import os
import re
import sys

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAF = os.path.join(HERE, "refs", "SAF")


def load_block():
    """从 model.py 抽出 Attention/Block，绕过 pytorch_transformers 依赖。"""
    src = open(os.path.join(SAF, "models", "model.py")).read()
    m = re.search(r"def gelu.*?\n(?=def weights_init_kaiming)", src, re.S)
    ns = {"torch": torch, "nn": nn, "math": __import__("math")}
    exec("import torch, math\nimport torch.nn as nn\n" + m.group(0), ns)
    return ns["Attention"], ns["Block"]


def check1_reshape():
    print("== ① L59 reshape 是否为干净 permute ==")
    B, N, C, H = 1, 2, 4, 3
    av = torch.arange(B * H * N * C).float().reshape(B, H, N, C)
    saf = av.transpose(1, 2).reshape(B, N, C, -1).permute(3, 0, 1, 2)   # SAF L59
    ok = av.permute(1, 0, 2, 3)                                          # 干净 permute
    print("   SAF 第0片 == head0 真实输出 ?", torch.equal(saf[0], av[:, 0]))
    print("   干净 permute 第0片 == head0 ?", torch.equal(ok[0], av[:, 0]))
    print("   第0片元素的原始 head 归属  :", [int(v) // (N * C) for v in saf[0].flatten()])
    print("   是确定性置换(元素集合不变)?",
          set(saf.flatten().tolist()) == set(av.flatten().tolist()))
    a2 = torch.arange(1 * 3 * 2 * 3).float().reshape(1, 3, 2, 3)         # H == C
    s2 = a2.transpose(1, 2).reshape(1, 2, 3, -1).permute(3, 0, 1, 2)
    print("   H==C 时退化为干净转置?      ", torch.equal(s2[0], a2[:, 0]))
    assert not torch.equal(saf[0], av[:, 0]), "预期错位, 实测相等"


def check2_shapes():
    print("\n== ② Block 端到端形状 ==")
    Attention, Block = load_block()
    B, N, C, K = 4, 7, 768, 10
    blk = Block(dim=C, num_heads=K, mlp_ratio=0.0, qkv_bias=False, qk_scale=None,
                drop=0.0, attn_drop=0.0, drop_path=0.0, norm_layer=nn.LayerNorm)
    x = torch.randn(B, N, C)
    mask = torch.ones(B, N)
    mask[:, 5:] = 0
    parts, attn = blk(x, mask)
    print("   parts: tuple(len=%d), 每元素 %s" % (len(parts), tuple(parts[0].shape)))
    print("   attn : %s  (B,K,N,N)" % (tuple(attn.shape),))
    print("   qkv.weight %s == (dim*K*3, dim) %s" %
          (tuple(blk.attn.qkv.weight.shape), (C * K * 3, C)))
    print("   scale %.6f == dim^-0.5 %.6f" % (blk.attn.scale, C ** -0.5))
    bn = nn.BatchNorm1d(C)
    f = torch.stack((bn(x[:, 0, :]),) + tuple(bn(p[:, 0, :]) for p in parts), dim=1)
    print("   stack -> %s  (B, 1+K, D)" % (tuple(f.shape),))
    print("   Block 参数量 %.2fM (其中 proj %.2fM 未被 forward 调用)" %
          (sum(p.numel() for p in blk.parameters()) / 1e6,
           blk.attn.proj.weight.numel() / 1e6))
    assert len(parts) == K and tuple(f.shape) == (B, 1 + K, C)


def _l2norm(x):
    return x / torch.pow(x, 2).sum(dim=-1, keepdim=True).sqrt()


def _div1(x):                                    # SAF metric.py L149
    x = _l2norm(x)
    g = x.bmm(x.transpose(1, 2))
    g = g.masked_fill((torch.eye(x.size(1)) > 0.5).repeat(g.size(0), 1, 1), 0.0)
    return torch.stack([torch.norm(v, p=2) for v in g]).mean() / (x.size(1) ** 2)


def _div2(f):                                    # SAF metric.py L161
    B, P, _ = f.size()
    fn = F.normalize(f, dim=2)
    return (torch.sum(torch.matmul(fn, fn.transpose(1, 2))) - B * P) / (P * (P - 1))


def check3_diversity():
    print("\n== ③ diversity_loss 与 diversity_loss2 是否等价 ==")
    torch.manual_seed(1)
    cases = {
        "随机":  torch.randn(4, 10, 768),
        "全同":  torch.randn(4, 1, 768).repeat(1, 10, 1),
        "正交":  torch.eye(10).unsqueeze(0).repeat(4, 1, 1).repeat(1, 1, 77)[:, :, :768],
    }
    same = True
    for name, x in cases.items():
        a, b = _div1(x).item(), _div2(x).item()
        print("   %-4s diversity_loss=%+.6f  diversity_loss2=%+.6f" % (name, a, b))
        same &= abs(a - b) < 1e-6
    print("   -> 等价?", same, " (loss2 可为负 => Frobenius 范数 vs 有符号求和)")
    assert not same, "预期不等价, 实测等价"


def check4_cmpm_broadcast():
    print("\n== ④ compute_cmpm_loss L238 广播方向是否安全 ==")
    lab = torch.tensor([0, 0, 1, 2, 2, 2])
    mf = ((lab.reshape(-1, 1) - lab.reshape(1, -1)) == 0).float()
    saf = mf / mf.norm(dim=1)                       # SAF 写法, 沿列广播
    row = mf / mf.norm(dim=1, keepdim=True)         # 意图: 逐行归一
    print("   SAF 写法 == 逐行归一 ?", torch.allclose(saf, row))
    print("   原因: mask 对称, mask[i,j]=1 => norm[i]==norm[j]; mask=0 处恒为 0")
    assert torch.allclose(saf, row)


if __name__ == "__main__":
    if not os.path.isdir(SAF):
        sys.exit("未找到 refs/SAF, 请先按执行文档 §3 克隆")
    check1_reshape()
    check2_shapes()
    check3_diversity()
    check4_cmpm_broadcast()
    print("\n[OK] 四项核对全部通过 (torch %s)" % torch.__version__)
