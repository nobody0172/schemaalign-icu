#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T6 · 跨库生理信号迁移 —— 对齐质量如何影响下游模型的跨库迁移。

为什么做这个 (外审意见):
  论文此前只评「对齐本身好不好」, 没有证明对齐好坏**会影响下游**。
  这一步把结论落到一个真正的多中心生理时间序列任务上:
  在 MIMIC-IV 上训练一个只吃「统一概念通道」的时序模型, 零样本迁移到 CareVue 与 eICU,
  唯一变量是**目标库的字段被哪种对齐方案填进通道**。

  oracle       gold 对                     —— 上界
  exact        归一化名精确匹配             —— 弱基线
  llm          Direct-LLM top-1 全部接受    —— 不弃权
  llm_abstain  低于 θ 的判 UNKNOWN, 通道留空 —— 本文

  预期: llm_abstain > llm, 因为「把错的字段填进通道」比「留空」更伤下游 ——
  这正是引言里「错配通道是信号层面的缺陷」那句话的实测检验。
  若不成立, 如实报告负结果。

通道只取**床旁连续监测**表 (chartevents / vitalPeriodic / nurseCharting / respChart),
不取化验: 化验在 MIMIC 侧是 hadm 级键, 与 stay 级时间轴对不齐, 且与「信号通道」的叙事无关。

阶段 1  DuckDB: (stay, hour 0..23, field_key) -> 均值, 只扫 cohort 内 stay 与用到的字段
阶段 2  torch : 按方案组装 [stays, 24, K] 张量, 训练/迁移评测
C7: 全量落盘, 每阶段产物带 .done, 可断点续跑。
"""
import argparse, csv, json, os, time
import numpy as np

PROJ = "/root/autodl-tmp/projects/SchemaAlign-ICU"
PQ = os.path.join(PROJ, "data_parquet")
WORK = os.path.join(PROJ, "work")
OUT = os.path.join(PROJ, "outputs", "T6")
os.makedirs(OUT, exist_ok=True)

# 床旁连续监测表 (stay 级键)
SRC = {"mimic-iv":  [("m4_chartevents", "epoch")],
       "mimic-iii": [("m3_chartevents", "epoch")],
       "eicu":      [("eicu_vitalperiodic", "native"), ("eicu_nursecharting", "native"),
                     ("eicu_respcharting", "native")]}
COH = {"mimic-iv": "cohort_m4.parquet", "mimic-iii": "cohort_m3cv.parquet",
       "eicu": "cohort_eicu.parquet"}
H = 24


def load_align():
    a = {}
    for r in csv.DictReader(open(os.path.join(WORK, "alignments.csv"),
                                 newline="", encoding="utf-8")):
        a.setdefault((r["db"], r["variant"]), {}).setdefault(r["field_key"], r["concept"])
    return a


def channels(align, k):
    """通道 = MIMIC-IV oracle 覆盖到的 vital / 呼吸血气 概念, 按源域字段数取前 k。"""
    grp = {r["base_concept"]: r["group"] for r in csv.DictReader(
        open(os.path.join(WORK, "gold", "concepts.csv"), newline="", encoding="utf-8"))}
    import collections
    c = collections.Counter(v for v in align[("mimic-iv", "oracle")].values()
                            if grp.get(v) in ("vital", "respiratory_bloodgas"))
    return [x for x, _ in c.most_common(k)]


def stage1(db, fields):
    """每 (stay, hour, field) 的均值。t0: MIMIC 取该 stay 的最小 t_offset, eICU 用原生 offset。"""
    import duckdb
    dst = os.path.join(OUT, "hourly_%s.parquet" % db)
    if os.path.exists(dst + ".done"):
        print("[skip] stage1 %s" % db, flush=True); return dst
    c = duckdb.connect()
    c.execute("PRAGMA threads=8"); c.execute("PRAGMA memory_limit='24GB'")
    c.execute("PRAGMA temp_directory='%s'" % os.path.join(PROJ, "cache", "duckdb_tmp"))
    flist = ",".join("'%s'" % f.replace("'", "''") for f in fields)
    parts = []
    for tbl, mode in SRC[db]:
        p = os.path.join(PQ, "%s.parquet" % tbl)
        if not os.path.exists(p):
            continue
        parts.append("""SELECT stay_key, field_key, t_offset, value_num
                        FROM read_parquet('%s')
                        WHERE value_num IS NOT NULL AND field_key IN (%s)""" % (p, flist))
    if not parts:
        raise SystemExit("no source table for %s" % db)
    union = "\n UNION ALL \n".join(parts)
    coh = os.path.join(WORK, "field_catalog", COH[db])
    hexpr = "CAST(floor(e.t_offset/60.0) AS BIGINT)" if db == "eicu" else \
            "CAST(floor((e.t_offset - z.t0)/60.0) AS BIGINT)"
    zero = "" if db == "eicu" else \
        ", z AS (SELECT stay_key, min(t_offset) AS t0 FROM ev GROUP BY stay_key)"
    join = "" if db == "eicu" else " JOIN z USING (stay_key)"
    sql = """
    WITH ev AS (%s)%s
    SELECT e.stay_key, %s AS hr, e.field_key, avg(e.value_num) AS v
    FROM ev e%s
    WHERE e.stay_key IN (SELECT stay_key FROM read_parquet('%s'))
    GROUP BY 1,2,3 HAVING hr BETWEEN 0 AND %d
    """ % (union, zero, hexpr, join.replace("JOIN z USING (stay_key)",
                                            "JOIN z ON z.stay_key=e.stay_key"),
           coh, H - 1)
    t0 = time.time()
    c.execute("COPY (%s) TO '%s' (FORMAT PARQUET)" % (sql, dst))
    n = c.execute("SELECT count(*) FROM read_parquet('%s')" % dst).fetchone()[0]
    open(dst + ".done", "w").write(str(n))
    print("[stage1] %-10s %8.1fs  %d 行 -> %s" % (db, time.time() - t0, n, dst), flush=True)
    return dst


def tensor(db, mapping, chans, stats=None):
    """[n_stays, H, K] + mask。同一概念多字段时取均值。"""
    import duckdb
    c = duckdb.connect(); c.execute("PRAGMA threads=8")
    coh = c.execute("SELECT stay_key, split, label_mortality FROM read_parquet('%s')"
                    % os.path.join(WORK, "field_catalog", COH[db])).fetchall()
    idx = {s: i for i, (s, _, _) in enumerate(coh)}
    ci = {c_: j for j, c_ in enumerate(chans)}
    X = np.zeros((len(coh), H, len(chans)), dtype=np.float32)
    C = np.zeros_like(X)
    rows = c.execute("SELECT stay_key, hr, field_key, v FROM read_parquet('%s')"
                     % os.path.join(OUT, "hourly_%s.parquet" % db)).fetchall()
    for sk, hr, fk, v in rows:
        con = mapping.get(fk)
        if con is None or con not in ci or sk not in idx:
            continue
        X[idx[sk], int(hr), ci[con]] += v
        C[idx[sk], int(hr), ci[con]] += 1
    M = (C > 0).astype(np.float32)
    X = np.divide(X, np.maximum(C, 1))
    if stats is None:                       # 只在源域训练分割上算 (C4)
        tr = np.array([sp == "train" for _, sp, _ in coh])
        mu = np.array([X[tr][:, :, j][M[tr][:, :, j] > 0].mean()
                       if M[tr][:, :, j].sum() else 0.0 for j in range(len(chans))])
        sd = np.array([X[tr][:, :, j][M[tr][:, :, j] > 0].std() or 1.0
                       if M[tr][:, :, j].sum() else 1.0 for j in range(len(chans))])
        stats = (mu, sd)
    mu, sd = stats
    X = (X - mu) / np.maximum(sd, 1e-6) * M
    y = np.array([lb for _, _, lb in coh], dtype=np.float32)
    sp = np.array([s for _, s, _ in coh])
    return np.concatenate([X, M], -1).astype(np.float32), y, sp, stats


class Net(__import__("torch").nn.Module):
    def __init__(self, k, h=64):
        import torch.nn as nn
        super().__init__()
        self.c = nn.Sequential(nn.Conv1d(k, h, 5, padding=2), nn.ReLU(),
                               nn.Conv1d(h, h, 5, padding=2), nn.ReLU())
        self.g = nn.GRU(h, h, batch_first=True)
        self.o = nn.Sequential(nn.Dropout(0.2), nn.Linear(h, 1))

    def forward(self, x):
        z = self.c(x.transpose(1, 2)).transpose(1, 2)
        _, hn = self.g(z)
        return self.o(hn[-1]).squeeze(-1)


def auroc(s, y):
    o = np.argsort(s); r = np.empty(len(s)); r[o] = np.arange(1, len(s) + 1)
    p = y.sum(); n = len(y) - p
    return float((r[y == 1].sum() - p * (p + 1) / 2) / (p * n)) if p and n else float("nan")


def auprc(s, y):
    o = np.argsort(-s); yy = y[o]; tp = np.cumsum(yy)
    pr = tp / np.arange(1, len(yy) + 1)
    return float((pr * yy).sum() / max(yy.sum(), 1))


def paired_boot(sa, sb, y, n_boot=2000, seed=0):
    """在**患者**上配对重采样, 给出 AUROC 差的 95% CI 与等价性判定。"""
    rng = np.random.default_rng(seed)
    sa, sb, y = np.asarray(sa), np.asarray(sb), np.asarray(y)
    n = len(y); d = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        if 0 < y[i].sum() < n:
            d.append(auroc(sb[i], y[i]) - auroc(sa[i], y[i]))
    d = np.array(d) * 100
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)), float(d.mean())


def train_one(Xs, ys, sps, a, seed):
    import torch
    torch.manual_seed(seed); np.random.seed(seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tr, va = sps == "train", sps == "val"
    net = Net(Xs.shape[-1]).to(dev)
    opt = torch.optim.Adam(net.parameters(), 1e-3)
    pos = float(ys[tr].sum()); neg = float((1 - ys[tr]).sum())
    lf = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(neg / max(pos, 1)).to(dev))
    Xt = torch.tensor(Xs[tr]).to(dev); yt = torch.tensor(ys[tr]).to(dev)
    Xv = torch.tensor(Xs[va]).to(dev)
    best, bstate, bad = -1, None, 0
    for ep in range(a.epochs):
        net.train(); perm = torch.randperm(len(Xt), device=dev)
        for i in range(0, len(Xt), a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad(); lf(net(Xt[b]), yt[b]).backward(); opt.step()
        net.eval()
        with torch.no_grad():
            v = auroc(net(Xv).cpu().numpy(), ys[va])
        if v > best:
            best, bstate, bad = v, {k: t.clone() for k, t in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= a.patience:
                break
    net.load_state_dict(bstate); net.eval()
    return net, best


def main(a):
    import torch
    align = load_align()
    chans = channels(align, a.k)
    print("通道 %d 个: %s" % (len(chans), ", ".join(chans)), flush=True)
    used = set()
    for (db, var), m in align.items():
        used |= {f for f, c in m.items() if c in chans}
    for db in SRC:
        stage1(db, sorted(used))

    Xs, ys, sps, st = tensor("mimic-iv", align[("mimic-iv", "oracle")], chans)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    nets, vals = [], []
    for sd in range(a.seeds):
        n_, v_ = train_one(Xs, ys, sps, a, sd)
        nets.append(n_); vals.append(100 * v_)
        print("  seed %d  val AUROC=%.2f" % (sd, 100 * v_), flush=True)
    print("  val AUROC over %d seeds: %.2f +- %.2f"
          % (a.seeds, float(np.mean(vals)), float(np.std(vals))), flush=True)

    rows, scores = [], {}
    for db in ("mimic-iii", "eicu"):          # 只报目标域: MIMIC-IV 上 LLM 只覆盖 val+test 分片, 不可比
        for var in ("oracle", "exact", "llm", "llm_abstain"):
            m = align.get((db, var), {})
            X, y, sp, _ = tensor(db, m, chans, st)
            per = []
            for net in nets:
                with torch.no_grad():
                    per.append(net(torch.tensor(X).to(dev)).cpu().numpy())
            au = [100 * auroc(p, y) for p in per]
            sm = np.mean(per, 0)              # 跨种子平均分数, 用于配对检验
            scores[(db, var)] = (sm, y)
            nch = len({c for c in m.values() if c in chans})
            rows.append({"domain": db, "alignment": var,
                         "AUROC_mean": round(float(np.mean(au)), 2),
                         "AUROC_sd": round(float(np.std(au)), 2),
                         "AUROC_ensemble": round(100 * auroc(sm, y), 2),
                         "AUPRC_ensemble": round(100 * auprc(sm, y), 2),
                         "channels_filled": nch, "n_stays": len(y),
                         "n_seeds": a.seeds,
                         "mortality_rate": round(100 * float(y.mean()), 2)})
            print("[%-10s] %-12s AUROC=%5.2f+-%.2f (ens %5.2f)  通道 %2d/%d"
                  % (db, var, np.mean(au), np.std(au), 100 * auroc(sm, y), nch, len(chans)),
                  flush=True)
        # 等价性检验: 弃权 vs 不弃权, 患者级配对 bootstrap; 边界 ±1 AUROC 点
        sa_, y_ = scores[(db, "llm")]; sb_, _ = scores[(db, "llm_abstain")]
        lo, hi, mu = paired_boot(sa_, sb_, y_)
        eq = (lo > -a.margin) and (hi < a.margin)
        rows.append({"domain": db, "alignment": "abstain vs llm (paired)",
                     "AUROC_mean": round(mu, 3), "AUROC_sd": "",
                     "AUROC_ensemble": "", "AUPRC_ensemble": "",
                     "channels_filled": "", "n_stays": len(y_), "n_seeds": a.seeds,
                     "mortality_rate": "", "CI_lo": round(lo, 3), "CI_hi": round(hi, 3),
                     "equivalence_margin": a.margin, "equivalent": bool(eq)})
        print("   Δ(弃权−不弃权) = %+.3f  95%%CI [%+.3f, %+.3f]  等价(±%.1f)=%s"
              % (mu, lo, hi, a.margin, eq), flush=True)
    cols = ["domain", "alignment", "AUROC_mean", "AUROC_sd", "AUROC_ensemble",
            "AUPRC_ensemble", "channels_filled", "n_stays", "n_seeds", "mortality_rate",
            "CI_lo", "CI_hi", "equivalence_margin", "equivalent"]
    with open(os.path.join(OUT, "table4_transfer.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    json.dump({"channels": chans, "val_auroc_mean": float(np.mean(vals)),
               "val_auroc_sd": float(np.std(vals)), "seeds": a.seeds,
               "equivalence_margin": a.margin, "n_boot": 2000},
              open(os.path.join(OUT, "meta.json"), "w"), indent=2)
    print("-> %s/table4_transfer.csv" % OUT, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=24)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--bs", type=int, default=256)
    p.add_argument("--patience", type=int, default=6)
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--margin", type=float, default=1.0)
    main(p.parse_args())
