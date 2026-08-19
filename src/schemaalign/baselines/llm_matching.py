# -*- coding: utf-8 -*-
"""基线 · Direct LLM JSON matching / LLMatch —— **复用 LLMatch 官方提示词**。

执行文档 §5 T4 把 Direct-LLM 列为「审稿人最会问的基线」, §3.2 又要求适配 LLMatch。
两者共用同一段提示词, 取自
  refs/LLMatch/benchmarks/column_matching_prompt_no_reasoning.md
**逐字复用官方模板**, 而不是自己编 —— 自编提示词会让基线强弱取决于我们的提示工程,
无法辩护。原模板的三条匹配准则 (entity similarity / contextual alignment /
data type compatibility) 与 `"mapping": "None"` 的未匹配机制全部保留。

两条基线的区别 (对应 LLMatch 论文的分阶段设计):
  Direct-LLM : 一次把全部候选概念交给 LLM, 直接输出匹配
  LLMatch    : 先 Rollup 到概念组 (schema preparation + candidate selection),
               再只在组内做列级匹配 (column alignment)

C5: 温度 0, 模板固定并存档 (sha256 写进 manifest)。
"""
import hashlib
import json
import os
import re

__all__ = ["LLMATCH_PROMPT", "build_direct_prompt", "build_llmatch_prompts",
           "parse_mappings", "prompt_sha"]

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PROMPT = os.path.join(_HERE, "..", "..", "..", "refs", "LLMatch",
                               "benchmarks", "column_matching_prompt_no_reasoning.md")


def _load_prompt(path=None):
    p = path or os.environ.get("SA_LLMATCH_PROMPT") or _DEFAULT_PROMPT
    p = os.path.normpath(p)
    if not os.path.exists(p):
        raise FileNotFoundError("未找到 LLMatch 官方提示词: %s" % p)
    return open(p, encoding="utf-8").read()


LLMATCH_PROMPT = _load_prompt()


def prompt_sha():
    return hashlib.sha256(LLMATCH_PROMPT.encode()).hexdigest()[:16]


def _field_line(row, key):
    """字段描述行。C1: 只用 label 等文本, **绝不含 itemid**。"""
    lab = (row.get("label") or key).split("|")[-1]
    parts = ["%s.%s" % ((row.get("src_table") or "unknown").split(".")[-1], lab)]
    d = []
    if row.get("dict_category"):
        d.append("category %s" % row["dict_category"])
    if row.get("unit_observed"):
        d.append("unit %s" % row["unit_observed"])
    if row.get("dtype_inferred"):
        d.append("type %s" % row["dtype_inferred"])
    if row.get("p50") not in (None, "", "na"):
        d.append("median %s" % row["p50"])
    return parts[0] + (" -- " + "; ".join(d) if d else "")


def build_direct_prompt(field_rows, field_keys, concept_lines):
    """一次给全部候选概念。field_rows/keys 为一批字段。"""
    src = "\n".join(_field_line(r, k) for r, k in zip(field_rows, field_keys))
    return (LLMATCH_PROMPT
            .replace("{{source_columns}}", src)
            .replace("{{target_columns}}", "\n".join(concept_lines)))


def build_llmatch_prompts(field_rows, field_keys, concepts_by_group):
    """LLMatch 的两阶段: 先选组, 再在组内匹配。返回 [(阶段, prompt, 元数据)]。"""
    groups = sorted(concepts_by_group)
    stage1 = (LLMATCH_PROMPT
              .replace("{{source_columns}}",
                       "\n".join(_field_line(r, k) for r, k in zip(field_rows, field_keys)))
              .replace("{{target_columns}}",
                       "\n".join("concept_group.%s -- %d candidate concepts"
                                 % (g, len(concepts_by_group[g])) for g in groups)))
    return [("rollup", stage1, {"groups": groups})]


_JSON = re.compile(r"\{.*\}", re.S)


def parse_mappings(text):
    """从 LLM 输出里抽 {source_column: [target, ...]}; 'None' 视为 UNKNOWN。"""
    if not text:
        return {}
    m = _JSON.search(text)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {}
    out = {}
    for e in d.get("mappings", []):
        s = e.get("source_column")
        if not s:
            continue
        tg = []
        for t in e.get("target_mappings", []):
            v = (t or {}).get("mapping")
            if v and v.strip().lower() != "none":
                tg.append(v.strip())
        out[s] = tg
    return out
