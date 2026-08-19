# -*- coding: utf-8 -*-
"""SchemaAlignModel —— 双视图 + 共享 facet 聚合。

保留 SAF Model.forward 的三处结构 (见 docs/plans/SAF二次开发方案_v1.md §1.1):
  ① 共享 Block          : 同一个 self.block 作用于两个视图
  ② 共享 BatchNorm      : SAF 定义了 bottleneck_text 却四处全调 bottleneck_image,
                          两视图的 global 与全部 K 个 facet 过同一个 BN。这层共享
                          论文未写但真实存在, 我们显式保留。
  ③ stack(dim=1)        : (B, 1+K, D), 下标 0 是 global, 1..K 是 facet

映射关系 (执行文档 §3.1):
  image (ViT)  -> lexical  view : FieldCard 文本 -> 冻结编码器 (离线缓存) -> (1+n) x d_frozen
  text  (BERT) -> evidence view : 属性 token     -> 可学习嵌入表        -> (1+m) x D

约束:
  C1  证据视图的属性里没有 itemid / labid / 任何数字型主键 —— 见 EVIDENCE_FIELDS
  C5  词法编码器完全冻结, 本模块只吃它的离线缓存; 词法侧唯一可训练参数是 lex_proj
"""
import torch
import torch.nn as nn

from .attention import Block, weights_init_kaiming

__all__ = ["EVIDENCE_FIELDS", "SchemaAlignConfig", "SchemaAlignModel"]

# 证据视图的 m 个属性 token (执行文档 §3.1 L104)。顺序固定, 不得含任何主键 (C1)。
EVIDENCE_FIELDS = (
    "unit_class",        # 单位类 (由实测 valueuom 众数归一而来)
    "dtype",             # 数据类型
    "table_provenance",  # 表来源族: 处方 / 实际给药 / 实验室 / 床旁 ...
    "category",          # 概念组
    "p01_bucket",        # 以下五项一律分桶后取离散 token, 不喂浮点
    "median_bucket",
    "p99_bucket",
    "obs_freq_bucket",
    "missing_bucket",
)
_FORBIDDEN = ("itemid", "labid", "item_id", "lab_id", "row_id", "hadm_id", "stay_id")


class SchemaAlignConfig:
    """默认值按已裁决项: D=256 (Q9)、不加残差 (Q8)、修正 reshape。"""

    def __init__(self, d_frozen=768, D=256, K=10, n_bucket=10,
                 n_unit=32, n_dtype=4, n_prov=8, n_cat=16,
                 max_lex_tokens=64, lex_proj_hidden=0, ev_dropout=0.1,
                 legacy_reshape=False, use_residual=False):
        self.d_frozen = d_frozen
        self.D = D
        self.K = K
        self.n_bucket = n_bucket
        self.n_unit, self.n_dtype, self.n_prov, self.n_cat = n_unit, n_dtype, n_prov, n_cat
        self.max_lex_tokens = max_lex_tokens
        self.lex_proj_hidden = lex_proj_hidden   # >0 时 lex_proj 用两层 MLP (缓解容量不对称)
        self.ev_dropout = ev_dropout
        self.legacy_reshape = legacy_reshape
        self.use_residual = use_residual

    def vocab(self, name):
        if name == "unit_class":
            return self.n_unit
        if name == "dtype":
            return self.n_dtype
        if name == "table_provenance":
            return self.n_prov
        if name == "category":
            return self.n_cat
        return self.n_bucket


class SchemaAlignModel(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        for f in EVIDENCE_FIELDS:                       # C1 静态断言
            assert not any(b in f for b in _FORBIDDEN), "C1 违规: %s" % f
        self.cfg = cfg

        # ---- 词法视图: 冻结编码器不在此处, 训练期只读离线缓存 (C5) ----
        if cfg.lex_proj_hidden > 0:
            self.lex_proj = nn.Sequential(
                nn.Linear(cfg.d_frozen, cfg.lex_proj_hidden), nn.GELU(),
                nn.Linear(cfg.lex_proj_hidden, cfg.D))
        else:
            self.lex_proj = nn.Linear(cfg.d_frozen, cfg.D)

        # ---- 证据视图: 可学习属性嵌入表 ----
        self.ev_cls = nn.Parameter(torch.zeros(1, 1, cfg.D))
        self.ev_emb = nn.ModuleDict(
            {f: nn.Embedding(cfg.vocab(f), cfg.D) for f in EVIDENCE_FIELDS})
        self.ev_pos = nn.Parameter(torch.zeros(1, 1 + len(EVIDENCE_FIELDS), cfg.D))
        self.ev_drop = nn.Dropout(cfg.ev_dropout)
        nn.init.trunc_normal_(self.ev_cls, std=0.02)
        nn.init.trunc_normal_(self.ev_pos, std=0.02)

        # ---- 共享 facet 聚合器 ----
        self.block = Block(dim=cfg.D, num_heads=cfg.K, qkv_bias=False,
                           norm_layer=nn.LayerNorm,
                           legacy_reshape=cfg.legacy_reshape,
                           use_residual=cfg.use_residual)

        # ---- 共享 BatchNorm (复刻 SAF 的 bottleneck_image 两侧共用) ----
        self.bn = nn.BatchNorm1d(cfg.D)
        self.bn.bias.requires_grad_(False)
        self.bn.apply(weights_init_kaiming)

    def encode_evidence(self, attr_ids):
        """attr_ids: dict[str, LongTensor(B,)] -> (B, 1+m, D)"""
        B = next(iter(attr_ids.values())).shape[0]
        toks = [self.ev_cls.expand(B, -1, -1)]
        for f in EVIDENCE_FIELDS:
            toks.append(self.ev_emb[f](attr_ids[f]).unsqueeze(1))
        return self.ev_drop(torch.cat(toks, dim=1) + self.ev_pos)

    def forward(self, lex_cached, lex_mask, attr_ids):
        """
        lex_cached : (B, 1+n, d_frozen)  冻结编码器的离线缓存, 不参与反传
        lex_mask   : (B, 1+n)            1=有效 0=padding
        attr_ids   : dict[str, (B,)]
        返回 (lex_out, ev_out, lex_attn, ev_attn, lex_f, ev_f)
             —— 与 SAF Model.forward 的返回签名逐位对应, 可直接喂给 Loss
        """
        L = self.lex_proj(lex_cached)                       # (B, 1+n, D)
        E = self.encode_evidence(attr_ids)                  # (B, 1+m, D)

        lex_out = (self.bn(L[:, 0, :]),)                    # 对应 SAF L158
        ev_out = (self.bn(E[:, 0, :]),)                     # 对应 SAF L159

        lex_parts, lex_attn = self.block(L, lex_mask)       # 对应 SAF L162
        ev_parts, ev_attn = self.block(E, None)             # 对应 SAF L163 (同一个 block)

        for k in range(len(lex_parts)):                     # 对应 SAF L164-166
            lex_out = lex_out + (self.bn(lex_parts[k][:, 0, :]),)
            ev_out = ev_out + (self.bn(ev_parts[k][:, 0, :]),)

        lex_f = torch.stack(lex_out, dim=1)                 # (B, 1+K, D)
        ev_f = torch.stack(ev_out, dim=1)
        return lex_out, ev_out, lex_attn, ev_attn, lex_f, ev_f

    @torch.no_grad()
    def field_repr(self, lex_cached, lex_mask, attr_ids):
        """两视图融合后的字段表示 (B, 1+K, D) —— 用于建概念原型与检索打分。"""
        _, _, _, _, lex_f, ev_f = self.forward(lex_cached, lex_mask, attr_ids)
        return 0.5 * (lex_f + ev_f)
