# -*- coding: utf-8 -*-
"""CMPM / CMPC / diversity —— 复用自 SAF utils/metric.py, 三处必要修改。

1. ``l2norm`` 加 eps。SAF L33-36 无 eps, facet 塌缩成零向量时会产生 NaN;
   我们 batch 小、facet 数多, 风险实际存在。
2. **不实现 ``diversity_loss2``**。执行文档 §3.1 称它与 ``diversity_loss`` 等价 ——
   实测不等价: 前者是 Frobenius 范数 (恒 >=0, 正交处取 0), 后者是有符号求和
   (随机输入 -0.0149, 可为负), 最小值点与除数 (K^2 vs K(K-1)) 均不同。
   见 scripts/local/verify_saf_semantics.py ③。论文只报 Frobenius 形式。
3. 去掉硬编码 ``.cuda()``, 全部按输入张量的 device 走。

保持不变 (逐行照抄): CMPM 的单侧归一投影、CMPC 的先投影再分类、
``Loss.forward`` 中 global 与 K 个 facet 等权求和的组合方式。
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

__all__ = ["l2norm", "SchemaAlignLoss"]

_EPS = 1e-12


def l2norm(x, eps=_EPS):
    return x / (torch.pow(x, 2).sum(dim=-1, keepdim=True).sqrt() + eps)


class SchemaAlignLoss(nn.Module):
    """labels = canonical concept id (SAF 里是 person identity)。"""

    def __init__(self, feature_size, num_concepts, use_cmpm=True, use_cmpc=True,
                 epsilon=1e-8):
        super().__init__()
        self.use_cmpm, self.use_cmpc, self.epsilon = use_cmpm, use_cmpc, epsilon
        self.num_classes = num_concepts
        self.W = nn.Parameter(torch.randn(feature_size, num_concepts))
        nn.init.xavier_uniform_(self.W.data, gain=1)

    # ---- SAF utils/metric.py L149, 加 device 安全 ----
    def diversity_loss(self, x):
        """x: (B, K, D) -> 标量。惩罚 Gram 矩阵去对角后的 Frobenius 范数。"""
        x = l2norm(x)
        gram = x.bmm(x.transpose(1, 2))
        eye = torch.eye(x.size(1), device=x.device, dtype=torch.bool)
        gram = gram.masked_fill(eye.unsqueeze(0), 0.0)
        return gram.flatten(1).norm(p=2, dim=1).mean() / (x.size(1) ** 2)

    # ---- SAF utils/metric.py L174 ----
    def compute_cmpc_loss(self, a_emb, b_emb, labels):
        crit = nn.CrossEntropyLoss(reduction="mean")
        W_norm = self.W / self.W.norm(dim=0)
        a_n = a_emb / a_emb.norm(dim=1, keepdim=True)
        b_n = b_emb / b_emb.norm(dim=1, keepdim=True)
        a_proj_b = torch.sum(a_emb * b_n, dim=1, keepdim=True) * b_n
        b_proj_a = torch.sum(b_emb * a_n, dim=1, keepdim=True) * a_n
        a_logits = torch.matmul(a_proj_b, W_norm)
        b_logits = torch.matmul(b_proj_a, W_norm)
        loss = crit(a_logits, labels) + crit(b_logits, labels)
        a_prec = torch.mean((torch.argmax(a_logits, 1) == labels).float())
        b_prec = torch.mean((torch.argmax(b_logits, 1) == labels).float())
        return loss, a_prec, b_prec

    # ---- SAF utils/metric.py L214 ----
    def compute_cmpm_loss(self, a_emb, b_emb, labels):
        B = a_emb.shape[0]
        lab = labels.reshape(B, 1)
        mask = (lab - lab.t()) == 0
        a_n = a_emb / a_emb.norm(dim=1, keepdim=True)
        b_n = b_emb / b_emb.norm(dim=1, keepdim=True)
        a_proj_b = torch.matmul(a_emb, b_n.t())          # 只归一被投影的一侧 (CMPM 原设计)
        b_proj_a = torch.matmul(b_emb, a_n.t())
        # SAF L238 写的是 mask.float()/mask.float().norm(dim=1) (沿列广播)。
        # 已验证与逐行归一完全等价 (mask 对称 => mask[i,j]=1 蕴含 norm[i]==norm[j]),
        # 此处用 keepdim=True 表达同一件事, 更不易被误读。
        mf = mask.float()
        mask_norm = mf / mf.norm(dim=1, keepdim=True)
        a2b = F.softmax(a_proj_b, 1) * (F.log_softmax(a_proj_b, 1)
                                        - torch.log(mask_norm + self.epsilon))
        b2a = F.softmax(b_proj_a, 1) * (F.log_softmax(b_proj_a, 1)
                                        - torch.log(mask_norm + self.epsilon))
        loss = a2b.sum(1).mean() + b2a.sum(1).mean()
        sim = torch.matmul(a_n, b_n.t())
        pos = torch.masked_select(sim, mask).mean()
        neg = torch.masked_select(sim, ~mask).mean()
        return loss, pos, neg

    # ---- SAF utils/metric.py L265 ----
    def forward(self, a_outputs, b_outputs, a_f, b_f, labels, lambda_div):
        """
        a_outputs / b_outputs : tuple(len=1+K), 每元素 (B, D)   [词法侧 / 证据侧]
        a_f / b_f             : (B, 1+K, D)
        labels                : (B,) 概念 id
        """
        cmpm = a_outputs[0].new_zeros(())
        cmpc = a_outputs[0].new_zeros(())
        a_prec = b_prec = pos = neg = a_outputs[0].new_zeros(())
        if self.use_cmpm:
            for i in range(len(a_outputs)):              # i=0 global, 1..K facet, 等权
                li, pos, neg = self.compute_cmpm_loss(a_outputs[i], b_outputs[i], labels)
                cmpm = cmpm + li
        if self.use_cmpc:
            for i in range(len(a_outputs)):
                li, a_prec, b_prec = self.compute_cmpc_loss(a_outputs[i], b_outputs[i], labels)
                cmpc = cmpc + li
        loss = cmpm + cmpc
        loss = loss + lambda_div * (self.diversity_loss(a_f[:, 1:])
                                    + self.diversity_loss(b_f[:, 1:]))
        return cmpm, cmpc, loss, a_prec, b_prec, pos, neg
