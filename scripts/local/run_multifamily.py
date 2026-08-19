#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三个 LLM 家族上的主结果 —— 回应「只测了一个模型家族」这条限制。

同一提示词(LLMatch 官方模板逐字)、同一温度 0、同一评测集、同一弃权配置
(dims/w 只在 MIMIC-IV 验证分割上标定过一次, 不为每个模型重标定 —— 否则就不是同一方法)。

输出: results/tables/table8_multifamily.csv
"""
import csv, json, os, sys
sys.path.insert(0, "src")
import numpy as np
exec(open("scripts/local/run_placement_matched.py").read().split('if __name__')[0])
from schemaalign.baselines.llm_matching import parse_mappings

FAM = [("gpt-4.1", "OpenAI", ""),
       ("deepseek-v3.2", "DeepSeek", "_deepseek-v3.2"),
       ("gemini-2.5-pro", "Google", "_gemini-2.5-pro")]


def pred_for(es, db, sp, suffix):
    p = "data/llm_baseline/direct_%s_%s%s.json" % (db, sp or "all", suffix)
    if not os.path.exists(p):
        return None
    raw = json.load(open(p)); valid = set(es.concepts); pred = {}
    for k, v in raw.items():
        if k == "_usage":
            continue
        mp = parse_mappings(v["text"])
        for fk, l, t in zip(v["keys"], v["labels"], v["tables"]):
            hit = mp.get("%s.%s" % (t, l)) or mp.get(l) or []
            pred[fk] = [c.split(".")[-1] for c in hit if c.split(".")[-1] in valid]
    for it in es.items:
        pred.setdefault(it["field_key"], [])
    return pred


if __name__ == "__main__":
    rows = []
    for model, fam, suf in FAM:
        for db, fn, sp in DBS:
            es = load_evalset(GOLD, CAT, db, fn, split=sp)
            pred = pred_for(es, db, sp, suf)
            if pred is None:
                print("[pending] %-16s %s" % (model, db)); continue
            lab = [1 if i["gold"] is not None else 0 for i in es.items]
            m = evaluate(es, pred, REPS)
            b = abstain_scores(es.items, pred, REPS, _spec, dims=())
            o = abstain_scores(es.items, pred, REPS, _spec, dims=DIMSEL, w=W)
            sb = [b[i["field_key"]] for i in es.items]; so = [o[i["field_key"]] for i in es.items]
            a0, a1 = 100 * auroc(sb, lab), 100 * auroc(so, lab)
            lo, hi, p = paired_delta_ci(sb, so, lab)
            n_over = sum(1 for it in es.items if it["gold"] is None
                         and (pred.get(it["field_key"]) or []))
            n_err = n_over + sum(1 for it in es.items if it["gold"] is not None
                                 and (pred.get(it["field_key"]) or [None])[0] != it["gold"])
            rows.append({"model": model, "family": fam, "domain": db,
                         "Recall@1": round(m["Recall@1"], 2),
                         "Precision": round(m["Precision"], 2),
                         "Coverage": round(m["Coverage"], 2),
                         "over_assignment_share_of_errors_%":
                             round(100 * n_over / max(n_err, 1), 1),
                         "AUROC_base": round(a0, 2), "AUROC_ours": round(a1, 2),
                         "delta": round(a1 - a0, 2), "paired_CI_lo": round(100 * lo, 2),
                         "paired_CI_hi": round(100 * hi, 2), "boot_p": round(p, 4),
                         "n_fields": len(es), "n_positive": sum(lab)})
            print("%-16s %-10s R@1=%5.1f P=%5.1f  AUROC %5.2f->%5.2f  Δ=%+.2f CI[%+.2f,%+.2f] p=%.4f"
                  % (model, db, m["Recall@1"], m["Precision"], a0, a1, a1 - a0,
                     100 * lo, 100 * hi, p))
    if rows:
        with open("results/tables/table8_multifamily.csv", "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print("\n-> results/tables/table8_multifamily.csv (%d 行)" % len(rows))
