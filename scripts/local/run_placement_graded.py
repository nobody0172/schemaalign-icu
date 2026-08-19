#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外审意见: 原位置对照同时改变了「位置」和「处理方式」——拒绝臂是**二值否决**,
弃权臂是**分级惩罚**, 因而无法把效应归因于位置本身。

本脚本让两臂使用**同一个分级惩罚** w·Σ_d V_d, 只改变消费方式:
  A 分级重排  : 用 −Σ V_d 对 LLM 返回的候选列表重新排序 (不删除任何候选)
  B 分级拒绝  : 当 w·Σ V_d ≥ κ 时丢弃候选; κ 在 MIMIC-IV **验证分割**上按 F1 标定 (C4)
  C 分级弃权  : 本文方法, s(j)=b(j)(1−w Σ V_d), 只用于排序/判弃权

维度、w、gate 实现、候选、标定集、测试字段全部相同。
输出: results/tables/table3_placement_graded.csv
"""
import csv, json, os, sys
import numpy as np
sys.path.insert(0, "src")
from schemaalign.match.abstain import abstain_scores, auroc
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import _spec
from schemaalign.match.metrics import evaluate
exec(open("scripts/local/run_placement_matched.py").read().split('if __name__')[0])


def sumV(it, c):
    r = violations(it, c)
    return 0.0 if r is None else r[0]


def graded_rerank(es, pred):
    """只重排, 不删除 —— 位置 A 的最弱形式。"""
    return {it["field_key"]: sorted(pred.get(it["field_key"], []),
                                    key=lambda c: sumV(it, c))
            for it in es.items}


def graded_reject(es, pred, kappa):
    """同一分级惩罚, 但用作阈值化的否决规则。"""
    out = {}
    for it in es.items:
        out[it["field_key"]] = [c for c in pred.get(it["field_key"], [])
                                if W * sumV(it, c) < kappa]
    return out


if __name__ == "__main__":
    # κ 在 MIMIC-IV val 上按 F1 标定 (C4)
    v = load_evalset(GOLD, CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
    vp = llm_pred(v, "mimic-iv", "val")
    best = (None, -1)
    for k in np.arange(0.01, 0.35, 0.01):
        m = evaluate(v, graded_reject(v, vp, float(k)), REPS)
        if m["F1"] > best[1]:
            best = (round(float(k), 3), m["F1"])
    kappa = best[0]
    print("κ* = %.3f (MIMIC-IV val, F1=%.1f), w=%.2f, dims=%s"
          % (kappa, best[1], W, "+".join(DIMSEL)), flush=True)

    rows = []
    for db, fn, sp in DBS:
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        pred = llm_pred(es, db, sp)
        lab = [1 if i["gold"] is not None else 0 for i in es.items]
        m0 = evaluate(es, pred, REPS)
        s0 = [abstain_scores(es.items, pred, REPS, _spec, dims=())[i["field_key"]]
              for i in es.items]
        a0 = 100 * auroc(s0, lab)

        variants = [
            ("A graded re-rank (reorder only)", graded_rerank(es, pred), None),
            ("B graded reject (kappa on val)", graded_reject(es, pred, kappa), None),
            ("C graded abstention (ours)", pred, DIMSEL)]
        for tag, p, dims in variants:
            m = evaluate(es, p, REPS)
            sc = [abstain_scores(es.items, p, REPS, _spec,
                                 dims=(dims or ()), w=W)[i["field_key"]]
                  for i in es.items]
            a = 100 * auroc(sc, lab)
            lo, hi, ple = paired_delta_ci(s0, sc, lab)
            rows.append({"domain": db, "variant": tag,
                         "Recall@1": round(m["Recall@1"], 2),
                         "dRecall@1": round(m["Recall@1"] - m0["Recall@1"], 2),
                         "Precision": round(m["Precision"], 2),
                         "OpenSet_AUROC": round(a, 2), "dAUROC": round(a - a0, 2),
                         "paired_CI_lo": round(100 * lo, 2),
                         "paired_CI_hi": round(100 * hi, 2),
                         "kappa": kappa if tag.startswith("B") else "",
                         "n_fields": len(es), "n_positive": sum(lab)})
            print("  [%-9s] %-34s dR@1=%+6.2f  dAUROC=%+6.2f  CI[%+.2f,%+.2f]"
                  % (db, tag, m["Recall@1"] - m0["Recall@1"], a - a0,
                     100 * lo, 100 * hi), flush=True)

    with open("results/tables/table3_placement_graded.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("-> results/tables/table3_placement_graded.csv")
