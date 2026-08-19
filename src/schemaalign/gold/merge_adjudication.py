# -*- coding: utf-8 -*-
"""T2d · 把仲裁结果回填进 gold / UNKNOWN 集。

来源标记 (gold_pairs.csv 的 evidence 列) 保持可区分, 便于论文按证据来源分层报告:
  3-source agreement                  三份公开映射一致, 自动通过
  structural: shared lab itemid space MIMIC-III/IV 化验主键同一性
  explicit table column               人口学, 表内显式列
  adjudicated:both_agree              两名独立标注者一致
  adjudicated:adjudicated             标注者分歧, 由仲裁者裁定

UNSURE 一律**不进 gold, 也不进 UNKNOWN**, 单独留档 —— 这是 idea §13 要求保留的一档。
"""
import csv
import json
import os

__all__ = ["merge"]


def merge(gold_dir, catalog_dir, result_json):
    d = json.load(open(result_json, encoding="utf-8"))
    A = d["assignments"]

    CATF = {"eicu": "field_catalog_eicu.csv", "mimic-iii": "field_catalog_m3cv.csv",
            "mimic-iv": "field_catalog_m4.csv"}
    cat, key2db = {}, {}
    for db, fn in CATF.items():
        for r in csv.DictReader(open(os.path.join(catalog_dir, fn),
                                     newline="", encoding="utf-8")):
            cat[(db, r["field_key"])] = r
            key2db.setdefault(r["field_key"], []).append(db)

    def db_of(chunk):
        return {"eicu": "eicu", "mimiciii": "mimic-iii", "mimiciv": "mimic-iv"}[
            chunk.rsplit("_", 1)[0]]

    gp = os.path.join(gold_dir, "gold_pairs.csv")
    rows = list(csv.DictReader(open(gp, newline="", encoding="utf-8")))
    cols = list(rows[0].keys())
    have = {(r["db"], r["field_key"]) for r in rows}
    grp = {r["base_concept"]: r["group"] for r in csv.DictReader(
        open(os.path.join(gold_dir, "concepts.csv"), newline="", encoding="utf-8"))}

    added, unknown, unsure, miss = [], [], [], 0
    for a in A:
        db = db_of(a["chunk"])
        c = cat.get((db, a["field_key"]))
        if c is None:
            miss += 1
            continue
        if a["concept"] == "UNSURE":
            unsure.append((db, a["field_key"], c.get("label", ""), a["reason"]))
            continue
        if a["concept"] == "UNKNOWN":
            unknown.append((db, c["src_table"], c.get("label") or a["field_key"],
                            a["field_key"], "adjudicated:" + a["source"], a["reason"]))
            continue
        if (db, a["field_key"]) in have:
            continue
        added.append({
            "base_concept": a["concept"], "group": grp.get(a["concept"], ""),
            "db": db, "field_key": a["field_key"], "method": a.get("method") or "unspecified",
            "src_table": c["src_table"], "unit_observed": c["unit_observed"],
            "p01": c["p01"], "p50": c["p50"], "p99": c["p99"], "n_rows": c["n_rows"],
            "evidence": "adjudicated:" + a["source"], "src_file": a["chunk"],
        })

    with open(gp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
        w.writerows([{k: r.get(k, "") for k in cols} for r in added])

    # 仲裁产出的 UNKNOWN 是**逐字段过目**的结果, 比自动推导的候选集可信得多。
    # ⚠️ 多轮仲裁 (主轮 / 药物轮) 必须**取并集**, 不能覆盖 —— 否则后一轮会抹掉前一轮。
    UH = ["db", "src_table", "label", "field_key", "evidence", "reason"]
    up = os.path.join(gold_dir, "unknown_set_adjudicated.csv")
    prev = []
    if os.path.exists(up):
        prev = [tuple(r[c] for c in UH) for r in csv.DictReader(
            open(up, newline="", encoding="utf-8"))]
    seen, merged = set(), []
    for row in prev + [tuple(x) for x in unknown]:
        k = (row[0], row[3])
        if k not in seen:
            seen.add(k); merged.append(row)
    with open(up, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(UH); w.writerows(merged)

    SH = ["db", "field_key", "label", "reason"]
    sp = os.path.join(gold_dir, "unsure_set.csv")
    prevs = []
    if os.path.exists(sp):
        prevs = [tuple(r[c] for c in SH) for r in csv.DictReader(
            open(sp, newline="", encoding="utf-8"))]
    seen2, merged2 = set(), []
    for row in prevs + [tuple(x) for x in unsure]:
        k = (row[0], row[1])
        if k not in seen2:
            seen2.add(k); merged2.append(row)
    with open(sp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(SH); w.writerows(merged2)

    return {"assignments": len(A), "gold_added": len(added),
            "unknown_this_round": len(unknown), "unknown_total": len(merged),
            "unsure_total": len(merged2), "not_in_catalog": miss}
