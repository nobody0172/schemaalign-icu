# -*- coding: utf-8 -*-
"""共享 facet 聚合模块 —— 改造自 SAF (ICASSP 2022) models/model.py。

与参考实现的三处差异, 每处都有据可查:

1. **L59 的 reshape 已修正**。SAF 原式
   ``(attn @ v).transpose(1,2).reshape(B,N,C,-1).permute(3,0,1,2)``
   不是干净的 permute, 而是一次头/通道错位的确定性重排 —— 第 0 个切片的元素
   来自原始第 0/1/2 三个头 (见 scripts/local/verify_saf_semantics.py ①)。
   该重排不影响论文主张 (确定性、两侧相同、qkv 可学习吸收), 但会让
   ``attn[:, k]`` 与 facet k 对不上, 从而毁掉 facet 注意力可视化。
   默认改为 ``permute(1,0,2,3)``; ``legacy_reshape=True`` 可复现 SAF 原版。

2. **不建 ``proj``**。SAF 的 ``Attention.proj`` (dim*K -> dim, K=10,D=768 时 5.90M 参数)
   定义了但 ``forward`` 从不调用, 却仍进优化器、仍吃 weight decay。

3. **``use_residual`` 默认 False**。执行文档 §3.1 写的是「注意力 + 残差 + norm」,
   但 SAF 源码 L92-97 只有 ``self.attn(self.norm1(x))``, 无残差, MLP 亦被注释。
   已裁决 (Q8): 与源码保持一致, 不加残差; 保留开关仅供消融。

保留 SAF 的刻意设计: ``head_dim = dim`` (每个头输出完整 dim 维), 因而
``scale = dim ** -0.5`` 而非 ``(dim / num_heads) ** -0.5``。
"""
import math

import torch
import torch.nn as nn

__all__ = ["Attention", "Block", "gelu", "weights_init_kaiming"]


def gelu(x):
    return x * 0.5 * (1.0 + torch.erf(x / math.sqrt(2.0)))


def weights_init_kaiming(m):
    """原样取自 SAF models/model.py L100。"""
    cls = m.__class__.__name__
    if cls.find("Linear") != -1:
        nn.init.kaiming_normal_(m.weight, a=0, mode="fan_out")
        if m.bias is not None:
            nn.init.constant_(m.bias, 0.0)
    elif cls.find("Conv") != -1:
        nn.init.kaiming_normal_(m.weight, a=0, mode="fan_in")
        if m.bias is not None:
            nn.init.constant_(m.bias, 0.0)
    elif cls.find("BatchNorm") != -1:
        if m.affine:
            nn.init.constant_(m.weight, 1.0)
            nn.init.constant_(m.bias, 0.0)


class Attention(nn.Module):
    """多头注意力, 每个头输出完整 ``dim`` 维, 用作 K 个 facet 的产生器。

    输入  x            : (B, N, C)
    输入  input_masks  : (B, N) 或 None, 1=有效 0=padding
    输出  x            : (K, B, N, C)
    输出  attn         : (B, K, N, N)   —— 修正 reshape 后, attn[:, k] 即 facet k 的注意力
    """

    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None,
                 attn_drop=0.0, legacy_reshape=False):
        super().__init__()
        self.num_heads = num_heads
        self.legacy_reshape = legacy_reshape
        head_dim = dim                      # SAF 刻意设计: 不除以 num_heads
        self.scale = qk_scale or head_dim ** -0.5
        self.qkv = nn.Linear(dim, dim * num_heads * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)

    def forward(self, x, input_masks=None):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]                  # 各 (B, K, N, C)
        attn = (q @ k.transpose(-2, -1)) * self.scale     # (B, K, N, N)
        if input_masks is not None:
            ext = input_masks.unsqueeze(1).unsqueeze(2).to(dtype=attn.dtype)
            attn = attn + (1.0 - ext) * -10000.0
        attn = self.attn_drop(attn.softmax(dim=-1))
        ctx = attn @ v                                    # (B, K, N, C)
        if self.legacy_reshape:                           # 复现 SAF 原版 (含错位)
            out = ctx.transpose(1, 2).reshape(B, N, C, -1).permute(3, 0, 1, 2)
        else:
            out = ctx.permute(1, 0, 2, 3)                 # (K, B, N, C)
        return out, attn


class Block(nn.Module):
    """LayerNorm -> Attention。无 MLP; 残差默认关闭 (Q8)。"""

    def __init__(self, dim, num_heads, qkv_bias=False, qk_scale=None,
                 attn_drop=0.0, norm_layer=nn.LayerNorm,
                 legacy_reshape=False, use_residual=False):
        super().__init__()
        self.norm1 = norm_layer(dim)
        self.attn = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias,
                              qk_scale=qk_scale, attn_drop=attn_drop,
                              legacy_reshape=legacy_reshape)
        self.use_residual = use_residual

    def forward(self, x, input_masks=None):
        """返回 (tuple(len=K) of (B,N,C), attn (B,K,N,N))，与 SAF Block 的接口一致。"""
        h, attn = self.attn(self.norm1(x), input_masks)
        if self.use_residual:
            h = h + x.unsqueeze(0)
        return tuple(h[i] for i in range(h.shape[0])), attn
