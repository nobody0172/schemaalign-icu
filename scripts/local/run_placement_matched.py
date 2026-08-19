#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受控的「同一信号、两个位置」对照 + 配对 bootstrap + 误差分解 + 锁定阈值工作点。

外审(gpt-5.6-sol)对方案的四条要求, 逐条实现:
  (a) 重排 vs 弃权必须在**完全相同**的候选、检查、标定数据与测试实例上比,
      同时报 ΔR@1 与**配对** ΔAUROC —— 否则「同一信号换个位置」读起来像事后补救。
  (c1) 主结果的显著性必须用**配对 bootstrap 的 Δ 置信区间**, 边缘 CI 是否重叠不是正确检验。
  (c2) 「过度指派是主要错误」必须给出误差分解: UNKNOWN 被强行指派 vs 可映射字段配错概念。
  (c3) 只报 AUROC 不是可操作的方法, 需要在**锁定阈值**下的工作点。

配置完全复用 data/gold/abstain_config.json (MIMIC-IV val 标定, C4), 本脚本不引入新超参。
输出: results/tables/table3_placement.csv, table2_paired_delta.csv,
      table2_error_decomp.csv, table2_operating_point.csv
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import parse_mappings
from schemaalign.gates.rules import FieldSpec, gate_all
from schemaalign.match.abstain import abstain_scores, auroc
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import _spec
from schemaalign.match.metrics import evaluate

GOLD, CAT = "data/gold", "data/field_catalog"
DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
CFG = json.load(open(os.path.join(GOLD, "abstain_config.json")))
DIMSEL, W = tuple(CFG["dims"]), CFG["w"]


def reps():
    m4 = {c["field_key"]: c for c in csv.DictReader(
        open(os.path.join(CAT, "field_catalog_m4.csv"), newline="", encoding="utf-8"))}
    best = {}
    for r in csv.DictReader(open(os.path.join(GOLD, "gold_pairs.csv"),
                                 newline="", encoding="utf-8")):
        if r["db"] != "mimic-iv" or r["src_table"] in ("", "table_column"):
            continue
        n = int(r["n_rows"] or 0); c = r["base_concept"]; row = m4.get(r["field_key"], {})
        if c not in best or n > best[c][0]:
            best[c] = (n, FieldSpec(
                db="mimic-iv", field_key=r["field_key"],
                raw_name=(row.get("label") or r["field_key"]).split("|")[-1],
                src_table=r["src_table"], unit_observed=r["unit_observed"] or None,
                dtype_inferred="numeric", p01=r["p01"], p50=r["p50"], p99=r["p99"],
                dtype_declared=bool((row.get("param_type") or "").strip()),
                specimen=row.get("specimen") or None))
    return {k: v[1] for k, v in best.items()}


REPS = reps()


def llm_pred(es, db, sp):
    raw = json.load(open("data/llm_baseline/direct_%s_%s.json" % (db, sp or "all")))
    valid = set(es.concepts); pred = {}
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


def violations(it, concept):
    """返回 (Σ_d V_d, max_d V_d) —— 与弃权判据用的是**同一个** gate_all 调用与同一组维度。"""
    rep = REPS.get(concept)
    if rep is None:
        return None
    g = gate_all(_spec(it["row"], it["field_key"]), rep, concept_mode=True)
    v = {"unit": g.v_unit, "type": g.v_type, "specimen": g.v_specimen,
         "provenance": g.v_prov}
    vals = [v[d] for d in DIMSEL]
    return sum(vals), max(vals)


def rerank_pred(es, pred, mode):
    """位置 A —— 重排/拒绝: 不相容的候选被丢弃, 字段随之变 UNKNOWN。
    候选、检查、维度、标定集与位置 B 完全相同, 唯一差别是**用在哪一步**。

    mode='hard' : 任一 V_d == 1 (确定不相容) 即丢弃 —— 门控的标准语义
    mode='any'  : 任一 V_d > 0 (含"无法判定"的 0.5) 即丢弃 —— 保守上界
    """
    out = {}
    for it in es.items:
        k = it["field_key"]
        keep = []
        for c in pred.get(k, []):
            r = violations(it, c)
            if r is None:
                keep.append(c); continue
            ssum, smax = r
            drop = (smax >= 1.0) if mode == "hard" else (ssum > 0)
            if not drop:
                keep.append(c)
        out[k] = keep
    return out


def paired_delta_ci(sa, sb, lab, n_boot=2000, seed=0):
    """配对 bootstrap: 每次重采样**同一组字段索引**, 在同一样本上算两法之差。"""
    rng = np.random.default_rng(seed)
    sa, sb, lab = np.asarray(sa), np.asarray(sb), np.asarray(lab)
    n = len(lab); d = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        if 0 < lab[idx].sum() < n:
            d.append(auroc(sb[idx].tolist(), lab[idx].tolist())
                     - auroc(sa[idx].tolist(), lab[idx].tolist()))
    d = np.array(d)
    return (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)),
            float((d <= 0).mean()))


if __name__ == "__main__":
    place, paired, decomp, oper = [], [], [], []
    val_thr = None

    for db, fn, sp in DBS:
        es = load_evalset(GOLD, CAT, db, fn, split=sp)
        pred = llm_pred(es, db, sp)
        lab = [1 if i["gold"] is not None else 0 for i in es.items]
        base = abstain_scores(es.items, pred, REPS, _spec, dims=())
        ours = abstain_scores(es.items, pred, REPS, _spec, dims=DIMSEL, w=W)
        sb = [base[i["field_key"]] for i in es.items]
        so = [ours[i["field_key"]] for i in es.items]
        m0 = evaluate(es, pred, REPS)
        a0, a1 = 100 * auroc(sb, lab), 100 * auroc(so, lab)

        # ---- (c1) 配对 bootstrap 的 Δ 置信区间 ----
        lo, hi, p_le0 = paired_delta_ci(sb, so, lab)
        paired.append({"domain": db, "AUROC_base": round(a0, 2),
                       "AUROC_ours": round(a1, 2), "delta": round(a1 - a0, 2),
                       "paired_CI_lo": round(100 * lo, 2), "paired_CI_hi": round(100 * hi, 2),
                       "boot_p_delta_le_0": round(p_le0, 4),
                       "n_fields": len(es), "n_positive": sum(lab)})
        print("[%s] 配对 Δ=%+.2f  95%%CI [%+.2f, %+.2f]  p(Δ≤0)=%.4f"
              % (db, a1 - a0, 100 * lo, 100 * hi, p_le0), flush=True)

        # ---- (a) 受控的位置对照: 同候选/同检查/同维度/同标定集 ----
        for tau, tag in (("hard", "re-rank: reject on any hard violation (max V=1)"),
                         ("any", "re-rank: reject on any violation incl. undecidable")):
            rp = rerank_pred(es, pred, tau)
            mr = evaluate(es, rp, REPS)
            sr = [abstain_scores(es.items, rp, REPS, _spec, dims=())[i["field_key"]]
                  for i in es.items]
            ar = 100 * auroc(sr, lab)
            rlo, rhi, rp0 = paired_delta_ci(sb, sr, lab)
            place.append({"domain": db, "placement": tag,
                          "Recall@1": round(mr["Recall@1"], 2),
                          "dRecall@1": round(mr["Recall@1"] - m0["Recall@1"], 2),
                          "Precision": round(mr["Precision"], 2),
                          "OpenSet_AUROC": round(ar, 2), "dAUROC": round(ar - a0, 2),
                          "paired_CI_lo": round(100 * rlo, 2),
                          "paired_CI_hi": round(100 * rhi, 2)})
        place.append({"domain": db, "placement": "abstention evidence (ours)",
                      "Recall@1": round(m0["Recall@1"], 2), "dRecall@1": 0.0,
                      "Precision": round(m0["Precision"], 2),
                      "OpenSet_AUROC": round(a1, 2), "dAUROC": round(a1 - a0, 2),
                      "paired_CI_lo": round(100 * lo, 2), "paired_CI_hi": round(100 * hi, 2)})

        # ---- (c2) 误差分解 ----
        n_over = n_wrong = n_miss = n_ok = 0
        for it in es.items:
            top = (pred.get(it["field_key"]) or [None])[0]
            if it["gold"] is None:
                n_over += (top is not None)
            elif top is None:
                n_miss += 1
            elif top == it["gold"]:
                n_ok += 1
            else:
                n_wrong += 1
        err = n_over + n_wrong + n_miss
        decomp.append({"domain": db, "correct": n_ok,
                       "over_assignment (UNKNOWN given a concept)": n_over,
                       "wrong_concept (mappable, wrong target)": n_wrong,
                       "missed (mappable, abstained)": n_miss,
                       "over_share_of_errors_%": round(100.0 * n_over / err, 1) if err else 0,
                       "n_fields": len(es)})
        print("   误差分解: 过度指派 %d / 配错概念 %d / 漏判 %d  -> 过度指派占错误 %.1f%%"
              % (n_over, n_wrong, n_miss, 100.0 * n_over / err if err else 0), flush=True)

        # ---- (c3) 锁定阈值下的工作点 (θ 逐方法在 MIMIC-IV val 上锁定, C4) ----
        if val_thr is None:
            v = load_evalset(GOLD, CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
            vp = llm_pred(v, "mimic-iv", "val")
            vl = [1 if i["gold"] is not None else 0 for i in v.items]
            val_thr = {}
            for tag, dims in (("LLM self-abstention", ()), ("+ checks (ours)", DIMSEL)):
                vs = abstain_scores(v.items, vp, REPS, _spec, dims=dims, w=W)
                bf = (None, -1)
                for t in sorted({round(x, 4) for x in vs.values()}):
                    tp = sum(1 for i, y in zip(v.items, vl)
                             if vs[i["field_key"]] >= t and y == 1)
                    fp = sum(1 for i, y in zip(v.items, vl)
                             if vs[i["field_key"]] >= t and y == 0)
                    fn = sum(1 for i, y in zip(v.items, vl)
                             if vs[i["field_key"]] < t and y == 1)
                    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0
                    if f1 > bf[1]:
                        bf = (t, f1)
                val_thr[tag] = bf[0]
            print("   工作点阈值逐方法锁定于 MIMIC-IV val (C4): %s" % val_thr, flush=True)
        for tag, sc in (("LLM self-abstention", sb), ("+ checks (ours)", so)):
            th_m = val_thr[tag]
            tp = sum(1 for s, y in zip(sc, lab) if s >= th_m and y == 1)
            fp = sum(1 for s, y in zip(sc, lab) if s >= th_m and y == 0)
            fn = sum(1 for s, y in zip(sc, lab) if s < th_m and y == 1)
            tn = len(lab) - tp - fp - fn
            oper.append({"domain": db, "method": tag, "theta_locked": round(th_m, 4),
                         "Precision": round(100 * tp / (tp + fp), 2) if tp + fp else 0.0,
                         "Recall": round(100 * tp / (tp + fn), 2) if tp + fn else 0.0,
                         "F1": round(200.0 * tp / (2 * tp + fp + fn), 2) if tp else 0.0,
                         "UNKNOWN_detection_recall": round(100 * tn / (tn + fp), 2)
                         if tn + fp else 0.0, "n_fields": len(lab)})

    os.makedirs("results/tables", exist_ok=True)
    for name, rws in (("table3_placement", place), ("table2_paired_delta", paired),
                      ("table2_error_decomp", decomp), ("table2_operating_point", oper)):
        with open("results/tables/%s.csv" % name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(rws[0].keys())); w.writeheader(); w.writerows(rws)
        print("-> results/tables/%s.csv" % name)
