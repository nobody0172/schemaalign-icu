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


def concept_lines(concepts, groups):
    """目标侧：概念名 + 所属组。C3: 不含任何目标库字段名。"""
    return ["concept.%s -- group %s" % (c, groups.get(c, "other")) for c in concepts]


def run(db, catf, split, batch=40, cache=True):
    es = load_evalset(GOLD, CAT, db, catf, split=split)
    groups = {r["base_concept"]: r["group"] for r in csv.DictReader(
        open(os.path.join(GOLD, "concepts.csv"), newline="", encoding="utf-8"))}
    tgt = concept_lines(es.concepts, groups)
    tag = "" if MODEL == "gpt-4.1" else "_" + MODEL.replace("/", "-")
    cpath = os.path.join(OUTD, "direct_%s_%s%s.json" % (db, split or "all", tag))
    if cache and os.path.exists(cpath):
        raw = json.load(open(cpath))
    else:
        raw, usage_tot = {}, {"prompt_tokens": 0, "completion_tokens": 0}
        items = es.items
        for i in range(0, len(items), batch):
            chunk = items[i:i + batch]
            p = build_direct_prompt([c["row"] for c in chunk],
                                    [c["field_key"] for c in chunk], tgt)
            txt, us = chat(p)
            raw[str(i)] = {"keys": [c["field_key"] for c in chunk],
                           "labels": [(c["row"].get("label") or c["field_key"]).split("|")[-1]
                                      for c in chunk],
                           "tables": [(c["row"].get("src_table") or "unknown").split(".")[-1]
                                      for c in chunk],
                           "text": txt}
            for k in usage_tot:
                usage_tot[k] += us.get(k, 0)
            print("   %s %s: %d/%d 字段" % (db, split or "all",
                                           min(i + batch, len(items)), len(items)), flush=True)
        raw["_usage"] = usage_tot
        json.dump(raw, open(cpath, "w"), ensure_ascii=False)

    # 解析：LLM 返回的 source_column 形如 "table.label"，映射回 field_key
    pred = {}
    valid = set(es.concepts)
    for k, v in raw.items():
        if k == "_usage":
            continue
        mp = parse_mappings(v["text"])
        for fk, lab, tb in zip(v["keys"], v["labels"], v["tables"]):
            hit = mp.get("%s.%s" % (tb, lab)) or mp.get(lab) or []
            cs = [c.split(".")[-1] for c in hit]
            pred[fk] = [c for c in cs if c in valid]
    for it in es.items:
        pred.setdefault(it["field_key"], [])
    return es, pred, raw.get("_usage", {})


if __name__ == "__main__":
    print("模型 %s | LLMatch 提示词 sha256=%s" % (MODEL, prompt_sha()))
    rows = []
    # val 分割用于按 C4 标定弃权判据的超参; test/目标域用于报告
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "val"),
                       ("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None),
                       ("eicu", "field_catalog_eicu.csv", None)):
        es, pred, usage = run(db, fn, sp)
        m = evaluate(es, pred)
        m.update({"method": "Direct LLM JSON matching (%s)" % MODEL, "domain": db,
                  "prompt_sha": prompt_sha(), **usage})
        rows.append(m)
        print("[%s] R@1=%.1f P=%.1f R=%.1f F1=%.1f Cov=%.1f  (n=%d, pos=%d, tok=%s)"
              % (db, m["Recall@1"], m["Precision"], m["Recall"], m["F1"], m["Coverage"],
                 m["n_fields"], m["n_positive"], usage.get("prompt_tokens", "?")), flush=True)
    cols = ["method", "domain", "Recall@1", "Precision", "Recall", "F1", "Coverage",
            "OpenSet_AUROC", "n_fields", "n_positive", "n_unknown", "prompt_sha",
            "prompt_tokens", "completion_tokens"]
    os.makedirs("results/tables", exist_ok=True)
    suffix = "" if MODEL == "gpt-4.1" else "_" + MODEL.replace("/", "-")
    with open("results/tables/table2_llm_baseline%s.csv" % suffix, "w",
              newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("\n-> results/tables/table2_llm_baseline%s.csv" % suffix)
