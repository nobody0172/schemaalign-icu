#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基线 · Direct LLM JSON matching + LLMatch（执行文档 §5 T4）。

提示词**逐字复用 LLMatch 官方模板** `refs/LLMatch/benchmarks/column_matching_prompt_no_reasoning.md`
（sha256 存档），不自编——否则基线强弱取决于我们的提示工程，无法辩护。

模型选择：`gpt-4.1`，与金标准仲裁所用的标注者（Claude）**不同家族**，
部分缓解台账 E21「gold 与方法共享知识源」的质疑（须在论文中如实说明仍非完全独立）。

C5：temperature=0，模板固定并存档。
C1：提示词里只出现 label 等文本，**不含任何 itemid**（`_field_line` 内保证）。
"""
import csv
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import (build_direct_prompt, parse_mappings,  # noqa
                                                prompt_sha)
from schemaalign.match.evalset import load_evalset
from schemaalign.match.metrics import evaluate

GOLD, CAT = "data/gold", "data/field_catalog"
OUTD = "data/llm_baseline"
os.makedirs(OUTD, exist_ok=True)
KEY = os.environ["SA_LLM_API_KEY"]
BASE = os.environ.get("SA_LLM_BASE_URL", "https://api.chatanywhere.org/v1")
MODEL = os.environ.get("SA_LLM_MODEL", "gpt-4.1")


# 中转站前置 Cloudflare, 会以 403 拦截 Python-urllib 的默认 User-Agent。
# 该 403 与请求长度、模型、配额均无关 —— 只与 UA 有关 (已二分验证)。
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def chat(prompt, retries=3):
    body = json.dumps({"model": MODEL, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json",
        "User-Agent": _UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"], d.get("usage", {})
        except Exception as e:
            if i == retries - 1:
                print("   [ERR] %s" % str(e)[:120], flush=True)
                return "", {}
            time.sleep(3 * (i + 1))
    return "", {}




def field_line_with_id(row, key):
    """与 llm_matching._field_line 相同, 但**附上原始 itemid** —— 仅用于记忆检验。"""
    lab = (row.get("label") or key).split("|")[-1]
    parts = ["%s.%s" % ((row.get("src_table") or "unknown").split(".")[-1], lab)]
    d = ["itemid %s" % key]                      # <== 唯一差别
    if row.get("dict_category"):
        d.append("category %s" % row["dict_category"])
    if row.get("unit_observed"):
        d.append("unit %s" % row["unit_observed"])
    if row.get("dtype_inferred"):
        d.append("type %s" % row["dtype_inferred"])
    if row.get("p50") not in (None, "", "na"):
        d.append("median %s" % row["p50"])
    return parts[0] + " -- " + "; ".join(d)


def concept_lines(concepts, groups):
    return ["concept.%s -- group %s" % (c, groups.get(c, "other")) for c in concepts]


def run_variant(db, catf, split, with_id, batch=40):
    from schemaalign.baselines.llm_matching import LLMATCH_PROMPT, _field_line
    es = load_evalset(GOLD, CAT, db, catf, split=split)
    groups = {r["base_concept"]: r["group"] for r in csv.DictReader(
        open(os.path.join(GOLD, "concepts.csv"), newline="", encoding="utf-8"))}
    tgt = concept_lines(es.concepts, groups)
    tag = "withid" if with_id else "noid"
    cpath = os.path.join(OUTD, "memcheck_%s_%s_%s.json" % (db, split or "all", tag))
    if os.path.exists(cpath):
        raw = json.load(open(cpath))
    else:
        raw = {}
        fl = field_line_with_id if with_id else _field_line
        for i in range(0, len(es.items), batch):
            ch = es.items[i:i + batch]
            src = "\n".join(fl(c["row"], c["field_key"]) for c in ch)
            p = (LLMATCH_PROMPT.replace("{{source_columns}}", src)
                 .replace("{{target_columns}}", "\n".join(tgt)))
            txt, _ = chat(p)
            raw[str(i)] = {"keys": [c["field_key"] for c in ch],
                           "labels": [(c["row"].get("label") or c["field_key"]).split("|")[-1] for c in ch],
                           "tables": [(c["row"].get("src_table") or "unknown").split(".")[-1] for c in ch],
                           "text": txt}
            print("   %s/%s %d/%d" % (db, tag, min(i + batch, len(es.items)), len(es.items)), flush=True)
        json.dump(raw, open(cpath, "w"), ensure_ascii=False)
    valid = set(es.concepts); pred = {}
    for k, v in raw.items():
        mp = parse_mappings(v["text"])
        for fk, l, t in zip(v["keys"], v["labels"], v["tables"]):
            hit = mp.get("%s.%s" % (t, l)) or mp.get(l) or []
            pred[fk] = [c.split(".")[-1] for c in hit if c.split(".")[-1] in valid]
    for it in es.items:
        pred.setdefault(it["field_key"], [])
    return es, pred


if __name__ == "__main__":
    print("C10 itemid 记忆检验 | 模型 %s | 温度 0 | 唯一变量: 字段描述是否含 itemid" % MODEL)
    rows = []
    print("\n%-11s %-14s %7s %7s %7s %7s" % ("域", "FieldCard", "R@1", "P", "F1", "Cov"))
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None)):
        for with_id in (False, True):
            es, pred = run_variant(db, fn, sp, with_id)
            m = evaluate(es, pred)
            tag = "含 itemid" if with_id else "不含(本文)"
            print("%-11s %-14s %7.1f %7.1f %7.1f %7.1f"
                  % (db, tag, m["Recall@1"], m["Precision"], m["F1"], m["Coverage"]))
            m.update({"domain": db, "fieldcard": tag}); rows.append(m)
    cols = ["domain", "fieldcard", "Recall@1", "Precision", "Recall", "F1", "Coverage",
            "n_fields", "n_positive"]
    with open("results/tables/table3_itemid_memory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, "")) for k in cols})
    print("\n-> results/tables/table3_itemid_memory.csv")
