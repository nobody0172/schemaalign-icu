# -*- coding: utf-8 -*-
"""T2b · 结构性自动补全 —— 用主键同一性, 不用名字匹配。

**为什么这不算污染**:
  MIMIC-III 与 MIMIC-IV 的**化验** itemid 共享同一编号空间: 交集 680 项,
  且 label 100% 一致 (证据台账 E3)。因此「同一个 itemid 在两库中是同一实体」
  是**结构性事实**, 与 LOINC crosswalk 同性质, 不是模糊匹配。
  它对我们的基线与方法都不可见 (C1 禁止 itemid 进 FieldCard),
  所以用它构造 gold 不会让 Exact-name 基线或单位门控消融虚高。

**边界**: 只对**化验**表生效。床旁监测侧 CareVue 与 MIMIC-IV 的 itemid 交集为 **0**
  (实测), 不存在可用的结构性同一性, 必须人工仲裁。
"""
import csv
import os

__all__ = ["structural_resolve"]


def structural_resolve(gold_dir, raw_catalog_dir, catalog_dir):
    R = lambda n: os.path.join(raw_catalog_dir, "01_field_catalog", n)
    m3 = {r["ITEMID"]: r for r in csv.DictReader(open(R("m3_d_labitems.csv"), encoding="utf-8"))}
    m4 = {r["itemid"]: r for r in csv.DictReader(open(R("m4_d_labitems.csv"), encoding="utf-8"))}
    shared = {k for k in set(m3) & set(m4)
              if m3[k]["LABEL"].strip().lower() == m4[k]["label"].strip().lower()}

    # CareVue 侧真实存在的化验字段 (T1.2 目录)
    cv = {r["field_key"]: r for r in csv.DictReader(
        open(os.path.join(catalog_dir, "field_catalog_m3cv.csv"), encoding="utf-8"))
        if r["src_table"] == "mimiciii.LABEVENTS"}

    qpath = os.path.join(gold_dir, "adjudication_queue.csv")
    rows = list(csv.DictReader(open(qpath, newline="", encoding="utf-8")))
    resolved, still = [], []
    for r in rows:
        need = set((r["dbs_missing"] or "").split("+")) - {""}
        if r["db"] == "mimic-iv" and "labevents" in r["src_table"] \
                and "mimic-iii" in need and r["field_key"] in shared \
                and r["field_key"] in cv:
            c = cv[r["field_key"]]
            resolved.append({
                "base_concept": r["base_concept"], "group": "", "db": "mimic-iii",
                "field_key": r["field_key"], "method": r["method"],
                "src_table": c["src_table"], "unit_observed": c["unit_observed"],
                "p01": c["p01"], "p50": c["p50"], "p99": c["p99"], "n_rows": c["n_rows"],
                "evidence": "structural: shared lab itemid space (label identical); LOINC=%s"
                            % (m3[r["field_key"]]["LOINC_CODE"] or "-"),
                "src_file": "bridge: m3_d_labitems x m4_d_labitems",
            })
        else:
            still.append(r)
            continue
        # 已补上 MIMIC-III 侧, 但若仍缺其它库, 该行必须留在队列中并更新 dbs_missing
        rest = need - {"mimic-iii"}
        if rest:
            r2 = dict(r)
            r2["dbs_missing"] = "+".join(sorted(rest))
            r2["dbs_covered"] = "+".join(sorted(
                set((r["dbs_covered"] or "").split("+")) - {""} | {"mimic-iii"}))
            r2["note"] = ((r.get("note") or "") +
                          " [MIMIC-III 侧已由 itemid 同一性结构性补全, 仅需补 %s]"
                          % "+".join(sorted(rest))).strip()
            still.append(r2)

    if resolved:
        gp = os.path.join(gold_dir, "gold_pairs.csv")
        old = list(csv.DictReader(open(gp, newline="", encoding="utf-8")))
        grp = {x["base_concept"]: x["group"] for x in csv.DictReader(
            open(os.path.join(gold_dir, "concepts.csv"), newline="", encoding="utf-8"))}
        for r in resolved:
            r["group"] = grp.get(r["base_concept"], "lab")
        with open(gp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(old[0].keys())); w.writeheader()
            w.writerows(old); w.writerows([{k: r.get(k, "") for k in old[0]} for r in resolved])

    with open(qpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(still)

    return {"shared_lab_itemids": len(shared),
            "structurally_resolved_pairs": len(resolved),
            "structurally_resolved_concepts": len({r["base_concept"] for r in resolved}),
            "queue_remaining_pairs": len(still),
            "queue_remaining_concepts": len({r["base_concept"] for r in still})}
