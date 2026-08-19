# -*- coding: utf-8 -*-
"""T2c · 仲裁工作表 —— 把任务反过来做。

**为什么反过来**:
  正着做 = 「对 96 个概念，逐个到目标库目录里搜对应字段」——96 次无界搜索，
  且同一个目标库字段可能被反复扫到，无法保证穷尽，也无法验证 UNKNOWN 集。
  反着做 = 「对目标库每一个高覆盖字段，指派一个概念或 UNKNOWN」——一次有界的穷尽扫描，
  同时天然产出 UNKNOWN 标注，且可核查覆盖率。

阈值: 只列覆盖 >= `min_coverage` 的字段。低于该阈值的字段在 24 小时窗口里几乎没有数据，
      即使映射正确也不进入下游，但**仍会计入 UNKNOWN 候选**（不丢弃，只是不强制人工过目）。

⚠️ 工作表**不提供任何按名字相似度排序或候选推荐**——那是待评测的 Exact-name 基线。
   排序只按 `src_table` + 覆盖率，这是组织顺序，不是判定线索。
"""
import csv
import os

__all__ = ["make_worksheets"]

DBS = {"eicu": "field_catalog_eicu.csv",
       "mimic-iii": "field_catalog_m3cv.csv",
       "mimic-iv": "field_catalog_m4.csv"}
# 药物表字段量大且已由 medication 组单独处理, 不进主工作表
SKIP_TABLES = {"eicu.infusionDrug", "mimiciv.hosp.prescriptions",
               "mimiciii.INPUTEVENTS_CV", "mimiciii.INPUTEVENTS_MV",
               "mimiciv.icu.inputevents"}


def make_worksheets(gold_dir, catalog_dir, out_dir, min_coverage=0.01):
    os.makedirs(out_dir, exist_ok=True)
    # 已确定的 gold, 工作表里标出来避免重复劳动
    done = set()
    gp = os.path.join(gold_dir, "gold_pairs.csv")
    if os.path.exists(gp):
        for r in csv.DictReader(open(gp, newline="", encoding="utf-8")):
            done.add((r["db"], r["field_key"]))
    # 还缺哪些概念, 逐库列出来放在工作表表头注释里
    need = {}
    q = os.path.join(gold_dir, "adjudication_queue.csv")
    if os.path.exists(q):
        for r in csv.DictReader(open(q, newline="", encoding="utf-8")):
            for d in (r["dbs_missing"] or "").split("+"):
                if d:
                    need.setdefault(d, set()).add(r["base_concept"])

    stats = {}
    for db, fn in DBS.items():
        rows = [r for r in csv.DictReader(
            open(os.path.join(catalog_dir, fn), newline="", encoding="utf-8"))
            if r["src_table"] not in SKIP_TABLES]
        keep = [r for r in rows if float(r["coverage"] or 0) >= min_coverage]
        keep.sort(key=lambda r: (r["src_table"], -float(r["n_rows"] or 0)))
        dst = os.path.join(out_dir, "worksheet_%s.csv" % db.replace("-", ""))
        cols = ["src_table", "field_key", "label", "abbreviation", "dict_category", "unit_observed", "dtype_inferred",
                "p01", "p50", "p99", "n_rows", "n_keys", "coverage",
                "already_gold", "concept", "note"]
        with open(dst, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, cols); w.writeheader()
            for r in keep:
                w.writerow({
                    "src_table": r["src_table"], "field_key": r["field_key"],
                    "label": r.get("label", ""), "abbreviation": r.get("abbreviation", ""),
                    "dict_category": r.get("dict_category", ""),
                    "unit_observed": r["unit_observed"], "dtype_inferred": r["dtype_inferred"],
                    "p01": r["p01"], "p50": r["p50"], "p99": r["p99"],
                    "n_rows": r["n_rows"], "n_keys": r["n_keys"],
                    "coverage": r["coverage"],
                    "already_gold": "Y" if (db, r["field_key"]) in done else "",
                    "concept": "", "note": "",
                })
        stats[db] = {"total_fields": len(rows), "to_review": len(keep),
                     "already_gold": sum(1 for r in keep if (db, r["field_key"]) in done),
                     "concepts_still_needed": len(need.get(db, ()))}
    # 待补概念清单
    with open(os.path.join(out_dir, "concepts_still_needed.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["db", "base_concept"])
        for d in sorted(need):
            for c in sorted(need[d]):
                w.writerow([d, c])
    return stats
