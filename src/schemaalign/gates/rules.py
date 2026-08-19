# -*- coding: utf-8 -*-
"""T3 · 确定性兼容性门控 V_unit / V_type / V_prov (执行文档 §5 T3, C6)。

指南 §2.1:
    S(j,c) = S_sem + β·S_onto + γ·S_stat − λ1·V_unit − λ2·V_type − λ3·V_prov
    硬拒: V_unit = 1 或 V_type = 1 -> S := −∞

三档取值 (执行文档 §5 T3):
    0    相容
    0.5  无法判定 -> 软约束
    1    明确冲突 -> 硬拒

C6: 规则必须是确定性的、**可打印的**。每次判定都返回 reason 字符串, 便于写进论文与错误分析。
"""
import collections
import re

from ..units.from_name import effective_unit
from ..units.table import default_table, normalize_unit

__all__ = ["FieldSpec", "GateResult", "provenance_family", "measurement_method",
           "v_method",
           "specimen_class", "v_unit", "v_type", "v_prov", "v_specimen",
           "gate_all", "apply_gate", "HARD_REJECT"]

HARD_REJECT = float("-inf")

FieldSpec = collections.namedtuple(
    "FieldSpec", ["db", "field_key", "raw_name", "src_table", "unit_observed",
                  "dtype_inferred", "p01", "p50", "p99", "dtype_declared", "specimen"])
# dtype_declared: 数据类型是否来自字典的 param_type (声明), 而非由 TRY_CAST 成功率推断。
# eICU 无 param_type, 只能推断; MIMIC 两库有。见 v_type 的说明。
FieldSpec.__new__.__defaults__ = (None,) * 9 + (False, None)


class GateResult(object):
    """hard_reject_prov 说明 —— 两份规格文档在此不一致:
         指南 §2.1 的公式框: 只有 V_unit=1 或 V_type=1 硬拒;
         执行文档 §5 T3 注释: V_prov=1 (处方 vs 给药 / 实验室 vs 床旁) 也硬拒。
       默认按执行文档 (更具体的实现规格) 取 True, 可关闭以复现指南口径。"""

    __slots__ = ("v_unit", "v_type", "v_prov", "v_specimen", "reasons", "hard_reject_prov")

    def __init__(self, vu, vt, vp, reasons, hard_reject_prov=True, vs=0.0):
        self.v_unit, self.v_type, self.v_prov, self.reasons = vu, vt, vp, reasons
        self.v_specimen = vs
        self.hard_reject_prov = hard_reject_prov

    @property
    def hard_reject(self):
        return (self.v_unit == 1 or self.v_type == 1 or self.v_specimen == 1
                or (self.hard_reject_prov and self.v_prov == 1))

    def __repr__(self):
        return ("GateResult(V_unit=%.1f, V_type=%.1f, V_prov=%.1f, V_specimen=%.1f, "
                "hard_reject=%s)" % (self.v_unit, self.v_type, self.v_prov,
                                     self.v_specimen, self.hard_reject))

    def explain(self):
        head = "V_unit=%.1f  V_type=%.1f  V_prov=%.1f  V_specimen=%.1f  ->  %s" % (
            self.v_unit, self.v_type, self.v_prov, self.v_specimen,
            "硬拒 (S := -inf)" if self.hard_reject else "通过, 计入软惩罚")
        return head + "\n" + "\n".join("    - " + r for r in self.reasons)


# ── 表来源族 ──────────────────────────────────────────────────────────────
# 三库的表 -> 来源族。族之间的兼容性由下面的矩阵决定, 全部确定性。
_FAMILY = {
    "mimiciv.hosp.labevents": "laboratory",
    "mimiciii.LABEVENTS": "laboratory",
    "eicu.lab": "laboratory",
    "mimiciv.icu.chartevents": "bedside_nursing",
    "mimiciii.CHARTEVENTS": "bedside_nursing",
    "eicu.nurseCharting": "bedside_nursing",
    "eicu.vitalPeriodic": "monitor",
    "eicu.vitalAperiodic": "monitor",
    "eicu.respiratoryCharting": "respiratory",
    "mimiciv.hosp.prescriptions": "prescription",
    "mimiciv.icu.inputevents": "administration",
    "mimiciii.INPUTEVENTS_CV": "administration",
    "mimiciii.INPUTEVENTS_MV": "administration",
    "eicu.infusionDrug": "administration",
}
# 明确冲突的族对 (硬拒)。依据: idea §7.3「处方字段和实际给药字段必须分开」
#                            + 指南 §3.1 难例 #8「一为实验室一为床旁」
_CONFLICT = {
    frozenset(("prescription", "administration")),
    frozenset(("laboratory", "bedside_nursing")),
    frozenset(("laboratory", "monitor")),
    frozenset(("laboratory", "administration")),
    frozenset(("laboratory", "respiratory")),
    frozenset(("administration", "bedside_nursing")),
    frozenset(("administration", "monitor")),
    frozenset(("prescription", "laboratory")),
    frozenset(("prescription", "bedside_nursing")),
    frozenset(("prescription", "monitor")),
}
# 同族群 (床旁监测的不同设备/记录方式) -> 相容
_SAME_GROUP = [{"bedside_nursing", "monitor", "respiratory"}]


def provenance_family(src_table):
    if not src_table:
        return None
    return _FAMILY.get(src_table)


# ── 测量方式 ──────────────────────────────────────────────────────────────
# 指南 §7.4: CanonicalConcept = (base_concept, measurement_method, specimen, unit, provenance)
# 指南 §3.1 Table 1 把「Non-Invasive BP vs Invasive BP」「MAP vs Arterial Line MAP」
# 归到 V_prov —— 但二者同在 eICU nurseCharting, 表来源分不开。
# 因此 provenance 取广义: (表来源族, 测量方式)。方式由字段名确定性抽取。
_METHOD_RULES = [
    (re.compile(r"non[\s\-_]?invasive|\bnibp\b|\bcuff\b|manual\s*bp", re.I), "noninvasive"),
    (re.compile(r"\barterial\s*line\b|\ba[\s\-]?line\b|\bibp\b|\binvasive\b|"
                r"\barterial\s*bp\b|systemic(systolic|diastolic|mean)", re.I), "invasive"),
    # 「设定值 vs 实测值」—— 盲测专家在 `Respiratory Rate (Set)` / `Respiratory Rate Set`
    # 上一致反对模型 (E47), 原规则只认 `^set_` / `_set$` / `setting`, 漏掉了括号与词尾形式。
    (re.compile(r"^\s*set[\s_]|[\s_]set\s*$|\(\s*set\s*\)|\bsetting\b|"
                r"\bset\s+(rr|peep|fio2|tv|vt)\b|\bdesired\b|\btarget\b", re.I), "set"),
    (re.compile(r"^total[\s_]|_total$|\bobserved\b|\bmeasured\b|\bspontaneous\b", re.I), "measured"),
    (re.compile(r"\bbedside\b|\bpoc\b|\bpoint[\s\-]of[\s\-]care\b|"
                r"\bfinger\s*stick\b|\bfingerstick\b|\bglucomet|\bcapillary\b", re.I), "bedside"),
    # 血氧: 动脉血气 SaO2 与 脉搏氧 SpO2 是两个概念 (E47 专家一致意见)
    (re.compile(r"\bsao2\b|\bsa\s*o2\b|arterial\s+(o2\s+)?sat", re.I), "bloodgas_sat"),
    (re.compile(r"\bspo2\b|\bsp\s*o2\b|pulse\s*ox|oximetr", re.I), "pulse_oximetry"),
]

# 概念目录里带方法修饰的概念名 —— 这些概念**本身**就指定了方式, 不能按"无修饰=默认"处理。
_METHOD_BEARING_CONCEPTS = ("spo2", "so2", "sao2")


def measurement_method(raw_name):
    """从字段名确定性抽测量方式; 抽不到返回 None (= unspecified)。"""
    if not raw_name:
        return None
    for rx, m in _METHOD_RULES:
        if rx.search(str(raw_name)):
            return m
    return None


def v_unit(a, b, table=None):
    """单位缺失时回退到名内抽取 (证据台账 E2: eICU 319 个字段单位列全空)。"""
    t = table or default_table()
    sa, ua, wa = effective_unit(a.unit_observed, a.raw_name)
    sb, ub, wb = effective_unit(b.unit_observed, b.raw_name)
    rel, why = t.relation(ua, ub)
    src = "单位来源 %s/%s" % (sa, sb)
    return ({"same": 0.0, "convertible": 0.0, "unknown": 0.5, "conflict": 1.0}[rel],
            "V_unit: %s — %s [%s; A:%s; B:%s]" % (rel, why, src, wa, wb))


def v_type(a, b):
    """
    ⚠️ 只有**两侧都是字典声明**的类型冲突才硬拒。

    实测: 若把 TRY_CAST 成功率**推断**出的类型也当作硬拒依据,
    门控会在 gold 对上产生 7.9~9.9% 的误拒, 其中 23/34 来自 V_type —
    典型是「数值以文本存储」的字段被推断成 categorical, 而概念代表是 numeric。
    误拒一个正确候选会同时丢一个真阳、造一个假阳, 代价远大于它挡掉的错配。
    """
    x, y = (a.dtype_inferred or "unknown"), (b.dtype_inferred or "unknown")
    if x == "unknown" or y == "unknown" or "mixed" in (x, y):
        return 0.5, "V_type: 无法判定 (%s vs %s)" % (x, y)
    if x == y:
        return 0.0, "V_type: 相容 (%s vs %s)" % (x, y)
    if a.dtype_declared and b.dtype_declared:
        return 1.0, "V_type: 冲突 — 两侧均为字典声明类型 (%s vs %s)" % (x, y)
    return 0.5, ("V_type: 无法判定 — 类型冲突 (%s vs %s) 但至少一侧由 TRY_CAST 推断, "
                 "降为软约束" % (x, y))


# ── 标本类型 ──────────────────────────────────────────────────────────────
# 指南 §7.4: CanonicalConcept = (base_concept, measurement_method, **specimen**, unit, provenance)
# 这一维此前漏实现。第二轮仲裁中标注者据标本类型判了 **86 条 UNKNOWN**:
# 腹水/胸水/脑脊液的白蛋白、葡萄糖、LDH 与血清同名同单位, **只有标本能区分**。
# 信号是现成且确定性的: MIMIC-IV d_labitems.fluid / MIMIC-III D_LABITEMS.FLUID。
_SPECIMEN = {
    "blood": "blood", "serum": "blood", "plasma": "blood", "whole blood": "blood",
    "urine": "urine",
    "ascites": "body_fluid", "pleural": "body_fluid", "joint fluid": "body_fluid",
    "other body fluid": "body_fluid", "fluid": "body_fluid", "bone marrow": "body_fluid",
    "cerebrospinal fluid": "csf", "cerebrospinal fluid (csf)": "csf", "csf": "csf",
    "stool": "stool",
}
_SPEC_NAME = re.compile(
    r"\b(ascites|ascitic|pleural|peritoneal|synovial|joint\s*fluid|"
    r"cerebrospinal|csf|urine|urinary|stool|bone\s*marrow)\b", re.I)


def specimen_class(spec, raw_name=None):
    """标本 -> 粗类 (blood / urine / body_fluid / csf / stool); 无信息返回 None。"""
    s = (spec or "").strip().lower()
    if s in _SPECIMEN:
        return _SPECIMEN[s]
    if s:
        for k, v in _SPECIMEN.items():
            if k in s:
                return v
    m = _SPEC_NAME.search(str(raw_name or ""))
    if m:
        w = m.group(1).lower()
        if "csf" in w or "cerebro" in w:
            return "csf"
        if "urin" in w:
            return "urine"
        if "stool" in w:
            return "stool"
        return "body_fluid"
    return None


def v_specimen(a, b):
    """标本类型明确不同 -> 1 (硬拒)。任一侧无标本信息 -> 0.5。"""
    sa = specimen_class(a.specimen, a.raw_name)
    sb = specimen_class(b.specimen, b.raw_name)
    if sa is None or sb is None:
        return 0.5, "V_specimen: 无法判定 (%s vs %s)" % (sa, sb)
    if sa == sb:
        return 0.0, "V_specimen: 相容 (%s)" % sa
    return 1.0, "V_specimen: 冲突 — 标本类型不同 (%s vs %s)" % (sa, sb)


def v_prov(a, b, concept_mode=False):
    """广义 provenance = (表来源族, 测量方式)。任一维明确冲突即判 1。

    ⚠️ concept_mode: **字段→概念** 匹配时必须置 True。
       表来源族冲突 (实验室 vs 床旁 等) 是**字段与字段之间**的关系 ——
       它刻画的是「同一个库里这两个字段来源不同, 不能合并」。
       但一个**统一概念**并不绑定于某一张表: 血糖既可来自化验也可来自床旁,
       概念代表恰好取自哪张表是抽样的偶然。若在字段→概念匹配上照搬该规则,
       会把大量正确匹配硬拒掉 —— 实测 R@1 从 67.6 掉到 51.4 (MIMIC-IV),
       53.0 掉到 38.9 (CareVue)。
       因此 concept_mode=True 时:
         · 测量方式冲突 仍判 1 (方式在两侧都能从名字确定性抽取, 是概念族的合法修饰)
         · 表来源族冲突 降为 0.5 (无法判定), 只作软惩罚
    """
    fa, fb = provenance_family(a.src_table), provenance_family(b.src_table)
    ma, mb = measurement_method(a.raw_name), measurement_method(b.raw_name)

    # ① 测量方式明确不同 -> 冲突 (指南 §3.1 Table 1 难例 #2 / #4)
    if ma and mb and ma != mb:
        return 1.0, "V_prov: 冲突 — 测量方式不同 (%s vs %s)" % (ma, mb)

    # ② 表来源族
    if fa is None or fb is None:
        return 0.5, "V_prov: 无法判定 — 表来源未登记 (%s vs %s)" % (a.src_table, b.src_table)
    if frozenset((fa, fb)) in _CONFLICT:
        if concept_mode:
            return 0.5, ("V_prov: 无法判定 — 来源族 %s vs %s; 概念不绑定单一表来源, "
                         "降为软约束" % (fa, fb))
        return 1.0, "V_prov: 冲突 — 来源族 %s vs %s" % (fa, fb)
    if fa == fb:
        if (ma or mb) and ma != mb:
            return 0.5, "V_prov: 无法判定 — 同来源族 %s, 但仅一侧标注方式 (%s vs %s)" % (fa, ma, mb)
        return 0.0, "V_prov: 相容 — 同来源族 %s, 测量方式 %s" % (fa, ma or "unspecified")
    for g in _SAME_GROUP:
        if fa in g and fb in g:
            return 0.0, "V_prov: 相容 — %s / %s 同属床旁记录" % (fa, fb)
    return 0.5, "V_prov: 无法判定 — %s vs %s 未在冲突表中" % (fa, fb)


def v_method(a, b):
    """V_method —— 由盲测专家数据 (E47) 直接催生的一维。

    残余标注错误里 6/9 是**测量方式混淆**: 床旁快速血糖被当成实验室血糖、
    呼吸机设定频率被当成实测呼吸频率、动脉 SaO2 被当成脉搏氧 SpO2。
    V_prov 本该抓这些, 但它以「表来源族」为主, 在字段→概念模式下被降为软约束,
    而概念目录里除 spo2/so2 外没有任何带方法修饰的条目。

    规则 (确定性、可打印):
      · 两侧方式都能抽出且不同            -> 1.0
      · 字段侧有显式方式修饰, 而概念侧没有, 且该概念不是"方式自带"的概念 -> 1.0
        (概念目录不含 set/bedside 变体, 所以带这类修饰的字段不属于任何概念)
      · 仅概念侧有修饰, 或两侧都没有      -> 0.0
    """
    ma, mb = measurement_method(a.raw_name), measurement_method(b.raw_name)
    cname = (b.raw_name or "").strip().lower()
    if ma and mb:
        if ma == mb:
            return 0.0, "V_method: 相容 — 双方均为 %s" % ma
        return 1.0, "V_method: 冲突 — 测量方式不同 (%s vs %s)" % (ma, mb)
    if ma and not mb:
        if any(k in cname for k in _METHOD_BEARING_CONCEPTS):
            return 0.5, "V_method: 无法判定 — 概念名自带方式修饰 (%s)" % cname
        return 1.0, ("V_method: 冲突 — 字段带显式方式修饰 (%s), 概念目录无对应变体" % ma)
    return 0.0, "V_method: 相容 — 字段无方式修饰"


def gate_all(a, b, table=None, hard_reject_prov=True, concept_mode=False):
    """concept_mode=True 用于字段→概念匹配 (见 v_prov 的说明); False 用于字段→字段。"""
    vu, ru = v_unit(a, b, table)
    vt, rt = v_type(a, b)
    vp, rp = v_prov(a, b, concept_mode=concept_mode)
    vs, rs = v_specimen(a, b)
    return GateResult(vu, vt, vp, [ru, rt, rp, rs], hard_reject_prov, vs)


def apply_gate(s_sem, gate, lam=(1.0, 1.0, 1.0)):
    """S = S_sem − λ1·V_unit − λ2·V_type − λ3·V_prov; 硬拒置 −inf。"""
    if gate.hard_reject:
        return HARD_REJECT
    l1, l2, l3 = lam
    return s_sem - l1 * gate.v_unit - l2 * gate.v_type - l3 * gate.v_prov
