#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文 Table 2 —— 全部方法在**同一评测集**上的可比主表。

为什么需要这个脚本:
  table2_main.csv (非 LLM 基线) 与 table2_llm_baseline.csv 此前跑在不同 gold 版本上
  (mimic-iii 250 vs 296 正例), 直接并排就是不可比。此处统一为
  (mimic-iv=test 分割, mimic-iii=全量, eicu=全量) —— 与 LLM 基线完全一致。

新增: SapBERT (领域预训练句向量) 作为**最强非 LLM 基线**。
  只用 MiniLM 当"冻结句向量"基线是自设稻草人; 台账 E39 已实测 SapBERT 更强,
  论文必须拿它来比。θ_open 仍按 C4 只在 MIMIC-IV 验证分割上标定。

输入: data/gold, data/field_catalog, data/embed (MiniLM), data/embed_ladder (SapBERT),
      data/llm_baseline/*.json
输出: results/tables/table2_final.csv
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from schemaalign.baselines.llm_matching import parse_mappings
from schemaalign.gates.rules import FieldSpec
from schemaalign.match.abstain import abstain_scores, auroc, bootstrap_ci
from schemaalign.match.baselines import (build_concept_loinc, exact_name_baseline,
                                         load_embeddings, ontology_baseline)
from schemaalign.match.evalset import load_evalset
from schemaalign.match.gated import _spec
from schemaalign.match.metrics import evaluate

GOLD, CAT, EMB, LAD = "data/gold", "data/field_catalog", "data/embed", "data/embed_ladder"
DBS = (("mimic-iv", "field_catalog_m4.csv", "test"),
       ("mimic-iii", "field_catalog_m3cv.csv", None),
       ("eicu", "field_catalog_eicu.csv", None))
CFG = json.load(open(os.path.join(GOLD, "abstain_config.json")))
DIMSEL, W = tuple(CFG["dims"]), CFG["w"]


def reps():
    """每个概念取 MIMIC-IV 侧行数最多的 gold 字段作代表 (C3: 只用源域)。"""
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
CL, LM = build_concept_loinc(GOLD, "data/raw_catalog")


def emb_scores_minilm(es):
    emb, cn, C = load_embeddings(EMB, es.db, "name")
    return _rank(es, emb, cn, C)


def emb_scores_sapbert(es):
    """阶梯产物: sapbert_<db>_name.npy + <db>_keys.csv + sapbert_concept.npy。
    概念侧用概念名 (与字段名同一文本空间, 见台账 E19)。"""
    E = np.load(os.path.join(LAD, "sapbert_%s_name.npy" % es.db)).astype("float32")
    keys = [r["field_key"] for r in csv.DictReader(
        open(os.path.join(LAD, "%s_keys.csv" % es.db), newline="", encoding="utf-8"))]
    C = np.load(os.path.join(LAD, "sapbert_concept.npy")).astype("float32")
    cn = [r["base_concept"] for r in csv.DictReader(
        open(os.path.join(GOLD, "concepts.csv"), newline="", encoding="utf-8"))]
    return _rank(es, dict(zip(keys, E)), cn, C)


def _rank(es, emb, cn, C):
    Cn = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    out = {}
    for it in es.items:
        v = emb.get(it["field_key"])
        if v is None:
            out[it["field_key"]] = []; continue
        vn = v / (np.linalg.norm(v) + 1e-9)
        s = Cn @ vn
        out[it["field_key"]] = [(float(s[i]), cn[i]) for i in np.argsort(-s)[:10]]
    return out


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


def apply_theta(raw, th):
    return {k: ([c for _, c in v] if v and v[0][0] >= th else []) for k, v in raw.items()}


SCORERS = [("Exact / normalized name", None, lambda es: exact_name_baseline(es)),
           ("Ontology only (LOINC)", None, lambda es: ontology_baseline(es, LM, CL)),
           ("Frozen encoder, general (MiniLM-L6)", "score", emb_scores_minilm),
           ("Frozen encoder, biomedical (SapBERT)", "score", emb_scores_sapbert)]


def openset_auroc_from_scores(es, raw):
    """开放集判据 = top-1 余弦分数 (未过阈值的原始分数)。"""
    lab = [1 if i["gold"] is not None else 0 for i in es.items]
    sc = [raw.get(i["field_key"])[0][0] if raw.get(i["field_key"]) else -1.0
          for i in es.items]
    lo, hi = bootstrap_ci(sc, lab, n_boot=400)
    return 100 * auroc(sc, lab), 100 * lo, 100 * hi


if __name__ == "__main__":
    # ---- θ_open 逐方法标定于 MIMIC-IV 验证分割 (C4) ----
    val = load_evalset(GOLD, CAT, "mimic-iv", "field_catalog_m4.csv", split="val")
    th = {}
    for nm, kind, fn in SCORERS:
        if kind != "score":
            th[nm] = None; continue
        raw = fn(val); best = (None, -1)
        for t in np.arange(-0.6, 1.001, 0.02):
            m = evaluate(val, apply_theta(raw, t), REPS)
            if m["F1"] > best[1]:
                best = (round(float(t), 3), m["F1"])
        th[nm] = best[0]
    print("θ_open 标定于 MIMIC-IV val (%d 字段/%d 正例), C4 合规: %s"
          % (len(val), sum(1 for i in val.items if i["gold"]), th), flush=True)

    rows = []
    for db, fn_cat, sp in DBS:
        es = load_evalset(GOLD, CAT, db, fn_cat, split=sp)
        lab = [1 if i["gold"] is not None else 0 for i in es.items]
        print("\n[%s] n=%d 正例=%d" % (db, len(es), sum(lab)), flush=True)
        for nm, kind, sfn in SCORERS:
            obj = sfn(es)
            if kind == "score":
                pred = apply_theta(obj, th[nm])
                a, lo, hi = openset_auroc_from_scores(es, obj)
            else:
                pred = obj
                sc = [1.0 if pred.get(i["field_key"]) else 0.0 for i in es.items]
                a = 100 * auroc(sc, lab)
                blo, bhi = bootstrap_ci(sc, lab, n_boot=400); lo, hi = 100 * blo, 100 * bhi
            m = evaluate(es, pred, REPS)
            rows.append({"method": nm, "domain": db, "theta": th[nm],
                         "Recall@1": round(m["Recall@1"], 2),
                         "Precision": round(m["Precision"], 2),
                         "F1": round(m["F1"], 2), "Coverage": round(m["Coverage"], 2),
                         "OpenSet_AUROC": round(a, 2), "CI_lo": round(lo, 2),
                         "CI_hi": round(hi, 2), "n_fields": len(es),
                         "n_positive": sum(lab)})
            print("  %-38s R@1=%5.1f P=%5.1f Cov=%5.1f AUROC=%5.1f [%.1f,%.1f]"
                  % (nm, m["Recall@1"], m["Precision"], m["Coverage"], a, lo, hi), flush=True)

        # ---- 检查是否与匹配器无关: 把同一批检查叠到最强非 LLM 匹配器 (SapBERT) 上 ----
        # base_conf = top-1 余弦 (匹配器自身置信度), 候选不过阈值 —— 与 LLM 侧口径一致:
        #   基线 = 匹配器自身置信度; 本文 = 该置信度 × (1 − w·Σ V_d)
        sraw = emb_scores_sapbert(es)
        spred = {k: [c for _, c in v] for k, v in sraw.items()}
        sconf = {k: (v[0][0] if v else 0.0) for k, v in sraw.items()}
        ms = evaluate(es, apply_theta(sraw, th["Frozen encoder, biomedical (SapBERT)"]), REPS)
        sc = list(abstain_scores(es.items, spred, REPS, _spec, dims=DIMSEL, w=W,
                                 base_conf=sconf).values())
        sc = [abstain_scores(es.items, spred, REPS, _spec, dims=DIMSEL, w=W,
                             base_conf=sconf)[i["field_key"]] for i in es.items]
        a = 100 * auroc(sc, lab); blo, bhi = bootstrap_ci(sc, lab, n_boot=400)
        rows.append({"method": "SapBERT + deterministic checks as abstention",
                     "domain": db, "theta": th["Frozen encoder, biomedical (SapBERT)"],
                     "Recall@1": round(ms["Recall@1"], 2),
                     "Precision": round(ms["Precision"], 2), "F1": round(ms["F1"], 2),
                     "Coverage": round(ms["Coverage"], 2), "OpenSet_AUROC": round(a, 2),
                     "CI_lo": round(100 * blo, 2), "CI_hi": round(100 * bhi, 2),
                     "n_fields": len(es), "n_positive": sum(lab)})
        print("  %-38s R@1=%5.1f P=%5.1f Cov=%5.1f AUROC=%5.1f [%.1f,%.1f]"
              % ("SapBERT + checks (ours, on encoder)", ms["Recall@1"], ms["Precision"],
                 ms["Coverage"], a, 100 * blo, 100 * bhi), flush=True)

        # ---- Direct-LLM 与 本文 (弃权证据) ----
        pred = llm_pred(es, db, sp)
        m = evaluate(es, pred, REPS)
        for tag, dims in (("Direct LLM (gpt-4.1, LLMatch prompt)", ()),
                          ("+ deterministic checks as abstention (ours)", DIMSEL)):
            s = abstain_scores(es.items, pred, REPS, _spec, dims=dims, w=W)
            sc = [s[i["field_key"]] for i in es.items]
            a = 100 * auroc(sc, lab)
            blo, bhi = bootstrap_ci(sc, lab, n_boot=400)
            rows.append({"method": tag, "domain": db, "theta": "",
                         "Recall@1": round(m["Recall@1"], 2),
                         "Precision": round(m["Precision"], 2),
                         "F1": round(m["F1"], 2), "Coverage": round(m["Coverage"], 2),
                         "OpenSet_AUROC": round(a, 2), "CI_lo": round(100 * blo, 2),
                         "CI_hi": round(100 * bhi, 2), "n_fields": len(es),
                         "n_positive": sum(lab)})
            print("  %-38s R@1=%5.1f P=%5.1f Cov=%5.1f AUROC=%5.1f [%.1f,%.1f]"
                  % (tag, m["Recall@1"], m["Precision"], m["Coverage"], a,
                     100 * blo, 100 * bhi), flush=True)

    os.makedirs("results/tables", exist_ok=True)
    with open("results/tables/table2_final.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("\n-> results/tables/table2_final.csv")
