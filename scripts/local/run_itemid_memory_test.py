#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C10 · itemid 记忆检验（指南 §4.2）。

**为什么必须做**：`mimic-code` 是 GitHub 上被大量引用的公开仓库，
`itemid 220045 = Heart Rate` 这类对应关系几乎肯定在冻结 LLM 的预训练语料里。
若 FieldCard 含 itemid 而结果显著变好，说明模型在靠记忆而非语义理解 —— 整个结果不可信。

设计：同一模型、同一提示词、同一评测集，唯一变量是字段描述里**是否带 itemid**。
  - 对照（本文设置，C1）：`chartevents.Heart Rate -- category Routine Vital Signs; unit bpm`
  - 实验（仅此实验破例）：`chartevents.220045 Heart Rate -- category ...`

**预期**：两者相当 ⇒ 模型没有靠记忆。若 +itemid 显著更好 ⇒ 必须在论文中如实披露。
本实验产出的 +itemid 版本**不进入任何其它结果**。
"""
import csv
import json
import os
import sys

sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import LLMATCH_PROMPT, parse_mappings, prompt_sha
from schemaalign.match.evalset import load_evalset
from schemaalign.match.metrics import evaluate

GOLD, CAT = "data/gold", "data/field_catalog"
OUTD = "data/llm_baseline"
sys.path.insert(0, "scripts/local")
from run_llm_baselines import chat  # noqa: E402


def field_line(row, key, with_itemid):
    lab = (row.get("label") or key).split("|")[-1]
    tb = (row.get("src_table") or "unknown").split(".")[-1]
    name = ("%s %s" % (key, lab)) if with_itemid else lab
    d = []
    if row.get("dict_category"):
        d.append("category %s" % row["dict_category"])
    if row.get("unit_observed"):
        d.append("unit %s" % row["unit_observed"])
    if row.get("dtype_inferred"):
        d.append("type %s" % row["dtype_inferred"])
    if row.get("p50") not in (None, "", "na"):
        d.append("median %s" % row["p50"])
    return "%s.%s%s" % (tb, name, (" -- " + "; ".join(d)) if d else "")


def run(db, fn, sp, with_itemid, concepts_lines, batch=40):
    es = load_evalset(GOLD, CAT, db, fn, split=sp)
    tag = "itemid" if with_itemid else "noitemid"
    cp = os.path.join(OUTD, "memtest_%s_%s_%s.json" % (tag, db, sp or "all"))
    if os.path.exists(cp):
        raw = json.load(open(cp))
    else:
        raw = {}
        for i in range(0, len(es.items), batch):
            ch = es.items[i:i + batch]
            src = "\n".join(field_line(c["row"], c["field_key"], with_itemid) for c in ch)
            p = (LLMATCH_PROMPT.replace("{{source_columns}}", src)
                 .replace("{{target_columns}}", "\n".join(concepts_lines)))
            txt, _ = chat(p)
            raw[str(i)] = {"keys": [c["field_key"] for c in ch],
                           "names": [field_line(c["row"], c["field_key"],
                                                with_itemid).split(" -- ")[0].split(".", 1)[1]
                                     for c in ch],
                           "tables": [(c["row"].get("src_table") or "u").split(".")[-1]
                                      for c in ch],
                           "text": txt}
            print("   %s %s: %d/%d" % (tag, db, min(i + batch, len(es.items)), len(es.items)),
                  flush=True)
        json.dump(raw, open(cp, "w"), ensure_ascii=False)
    valid = set(es.concepts); pred = {}
    for k, v in raw.items():
        mp = parse_mappings(v["text"])
        for fk, nm, tb in zip(v["keys"], v["names"], v["tables"]):
            # LLM 可能回显完整名、仅 itemid、或仅 label —— 逐个尝试, 否则会误判为 0
            cands = ["%s.%s" % (tb, nm), nm,
                     "%s.%s" % (tb, nm.split(" ", 1)[0]), nm.split(" ", 1)[0],
                     "%s.%s" % (tb, nm.split(" ", 1)[-1]), nm.split(" ", 1)[-1]]
            hit = next((mp[c] for c in cands if c in mp), [])
            pred[fk] = [c.split(".")[-1] for c in hit if c.split(".")[-1] in valid]
    for it in es.items:
        pred.setdefault(it["field_key"], [])
    return es, pred


if __name__ == "__main__":
    groups = {r["base_concept"]: r["group"] for r in csv.DictReader(
        open(os.path.join(GOLD, "concepts.csv"), newline="", encoding="utf-8"))}
    rows = []
    print("itemid 记忆检验 | 提示词 sha256=%s" % prompt_sha())
    for db, fn, sp in (("mimic-iv", "field_catalog_m4.csv", "test"),
                       ("mimic-iii", "field_catalog_m3cv.csv", None)):
        es0 = load_evalset(GOLD, CAT, db, fn, split=sp)
        cl = ["concept.%s -- group %s" % (c, groups.get(c, "other")) for c in es0.concepts]
        for wi in (False, True):
            es, pred = run(db, fn, sp, wi, cl)
            m = evaluate(es, pred)
            m.update({"domain": db, "fieldcard": "with itemid" if wi else "no itemid (ours)"})
            rows.append(m)
            print("[%s] %-18s R@1=%.1f P=%.1f F1=%.1f Cov=%.1f"
                  % (db, m["fieldcard"], m["Recall@1"], m["Precision"], m["F1"],
                     m["Coverage"]), flush=True)
    cols = ["domain", "fieldcard", "Recall@1", "Precision", "Recall", "F1", "Coverage",
            "n_fields", "n_positive"]
    with open("results/tables/table3_itemid_memory.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k, ""))
                        for k in cols})
    print("\n-> results/tables/table3_itemid_memory.csv")
