#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出四种对齐方案的 字段->概念 映射, 供下游迁移实验 (T6) 使用。

四种方案在下游实验里是**唯一变量**: 同一个模型、同一批目标库患者、同一套通道定义,
只有"目标库的哪个字段被填进哪个通道"不同。

  oracle      gold 对 (人工/仲裁裁定)            —— 上界
  exact       归一化字段名精确匹配               —— 弱基线
  llm         Direct-LLM 的 top-1, 全部接受      —— 不弃权
  llm_abstain Direct-LLM 的 top-1, 低于 θ 判 UNKNOWN 则**不填该通道** —— 本文

θ 为 MIMIC-IV 验证分割上锁定的值 (C4), 与论文工作点一致。
源域 (MIMIC-IV) 一律用 oracle —— 训练侧的对齐质量不是本实验的变量。

输出: work/alignments.csv  (db, variant, field_key, concept)
"""
import csv, json, os, sys
sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import parse_mappings
from schemaalign.gates.rules import FieldSpec
from schemaalign.match.abstain import abstain_scores
from schemaalign.match.baselines import exact_name_baseline
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import _spec

GOLD, CAT = "data/gold", "data/field_catalog"
CFG = json.load(open(os.path.join(GOLD, "abstain_config.json")))
DIMSEL, W = tuple(CFG["dims"]), CFG["w"]
THETA = 0.9          # 与 results/tables/table2_operating_point.csv 的锁定阈值一致 (MIMIC-IV val)
DBS = (("mimic-iv", "field_catalog_m4.csv", None),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
exec(open("scripts/local/run_placement_matched.py").read().split('if __name__')[0])


def llm_pred_full(db):
    """目标库用全量 LLM 输出; MIMIC-IV 把 val/test 两个分片合起来。"""
    pred = {}
    files = ["direct_%s_all.json" % db] if db != "mimic-iv" else \
            ["direct_mimic-iv_val.json", "direct_mimic-iv_test.json"]
    for fn in files:
        p = os.path.join("data/llm_baseline", fn)
        if not os.path.exists(p):
            continue
        for k, v in json.load(open(p)).items():
            if k == "_usage":
                continue
            mp = parse_mappings(v["text"])
            for fk, l, t in zip(v["keys"], v["labels"], v["tables"]):
                hit = mp.get("%s.%s" % (t, l)) or mp.get(l) or []
                if hit:
                    pred[fk] = [c.split(".")[-1] for c in hit]
    return pred


if __name__ == "__main__":
    rows = []
    for db, fn, _ in DBS:
        es = load_evalset(GOLD, CAT, db, fn)
        valid = set(es.concepts)
        gold = {it["field_key"]: it["gold"] for it in es.items if it["gold"]}
        for k, c in gold.items():
            rows.append({"db": db, "variant": "oracle", "field_key": k, "concept": c})
        for k, cs in exact_name_baseline(es).items():
            if cs:
                rows.append({"db": db, "variant": "exact", "field_key": k, "concept": cs[0]})
        raw = llm_pred_full(db)
        pred = {it["field_key"]: [c for c in raw.get(it["field_key"], []) if c in valid]
                for it in es.items}
        s = abstain_scores(es.items, pred, REPS, _spec, dims=DIMSEL, w=W)
        for it in es.items:
            k = it["field_key"]; cs = pred.get(k) or []
            if not cs:
                continue
            rows.append({"db": db, "variant": "llm", "field_key": k, "concept": cs[0]})
            if s[k] >= THETA:
                rows.append({"db": db, "variant": "llm_abstain", "field_key": k,
                             "concept": cs[0]})
    os.makedirs("work", exist_ok=True)
    with open("work/alignments.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["db", "variant", "field_key", "concept"])
        w.writeheader(); w.writerows(rows)
    import collections
    n = collections.Counter((r["db"], r["variant"]) for r in rows)
    for k in sorted(n):
        print("%-10s %-12s %4d 个字段" % (k[0], k[1], n[k]))
    print("-> work/alignments.csv (%d 行)" % len(rows))
