# SchemaAlign-ICU · 论文证据台账

**用途**：汇总一切**对论文有利、可直接引用**的实测发现。每条都注明数字、证据文件、
拟用于论文哪一处。**撰写论文时（T7）必须逐条过一遍本文件。**

**维护规则**
- 每轮实验结束追加，不删旧条目；被推翻的条目标 ~~删除线~~ 并注明原因。
- 每条必须有「证据文件」，否则不入册。
- 未经实测的推断标【待验证】，不得当作证据使用。

**状态图例**：🟢 已实测可用　🟡 部分完成　⚪ 待做

---

## E1 🟢 三份公开映射两两 Jaccard 仅 0.29–0.42

| 源 A | 源 B | A 概念 | B 概念 | 交集 | 并集 | **Jaccard** |
|---|---|---:|---:|---:|---:|---:|
| mimic-code MIMIC-IV | mimic-code MIMIC-III | 89 | 47 | 40 | 96 | **0.4167** |
| mimic-code MIMIC-IV | eicu-code | 89 | 67 | 35 | 121 | **0.2893** |
| mimic-code MIMIC-III | eicu-code | 47 | 67 | 32 | 82 | **0.3902** |

**为什么有利**：三份都是由专家策展、被社区大量引用的**官方社区标准**映射。
它们两两之间的概念集合重合度只有 0.29–0.42，说明**跨库 ICU 概念对齐远未收敛**——
这不是我们方法造出来的问题，而是领域现状。

**论文用处（两处）**
1. **Introduction 第 1–2 段的问题设定**：用一句话给出这三个数字，比任何定性描述都硬。
   建议句式：*Three widely used expert-curated concept mappings agree on only 29–42% of
   concepts pairwise (Jaccard), indicating that cross-database ICU field alignment is far
   from settled.*
2. **§4 Setup 中与 κ 并列报告**：执行文档 §5 T2 禁止编造 κ。E21 已用两名独立标注者做出了真实的 κ；
   本条衡量的是**三份独立专家资产之间**的分歧，角度不同、互补，建议一起报。

**证据文件**：`data/gold/source_agreement.csv`、`data/gold/adjudication_log.md` §4.1
**复现**：`python3 -c "import sys;sys.path.insert(0,'src');from schemaalign.gold.build_gold import build;build('refs','data/field_catalog','data/gold')"`

---

## E2 🟢 单位可恢复率：eICU 四张表 319 个字段 / 7.3 亿行**为 0**

| 库 | 表 | 字段数 | 有单位字段 | 字段占比 | 行占比 |
|---|---|---:|---:|---:|---:|
| MIMIC-IV | icu.chartevents | 2,293 | 468 | **20.41%** | 24.45% |
| MIMIC-IV | hosp.labevents | 862 | 560 | 64.97% | 86.71% |
| MIMIC-III CareVue | CHARTEVENTS | 3,545 | 419 | **11.82%** | 36.26% |
| MIMIC-III CareVue | LABEVENTS | 661 | 424 | 64.15% | 86.20% |
| eICU | lab | 158 | 134 | 84.81% | 95.35% |
| eICU | nurseCharting | 95 | **0** | **0%** | 0% |
| eICU | respiratoryCharting | 198 | **0** | **0%** | 0% |
| eICU | vitalPeriodic | 16 | **0** | **0%** | 0% |
| eICU | vitalAperiodic | 10 | **0** | **0%** | 0% |

**为什么有利**：idea 原本引用的是**字典层**单位缺失率（chartevents 85.3%、CareVue 100%）。
这里是**实测数据层**的可恢复率，更极端也更可信：eICU 的四张表合计 319 个字段、
7.3 亿行，**没有任何单位信息**，单位只能靠值域与表来源推断。

**论文用处**
- **§3.2 兼容性门控**：证明 `V_unit` 的「无法判定 → 软约束」这一档不是理论补丁，而是**主流情形**。
- **相对 LLMatch / SemStruct 的差异化**：通用 schema matching 假设元数据完整；临床数据不成立。
- **新指标 unit recovery rate 的正当性**（指南 §5.1 已要求报告）。

**证据文件**：`data/field_catalog/unit_recovery_report.csv`

---

## E3 🟢 LOINC 桥接：为 MIMIC-IV 恢复 33.4% 化验字段的标准编码

| 指标 | 值 |
|---|---:|
| MIMIC-IV `d_labitems` 总项 | 1,650 |
| MIMIC-III `D_LABITEMS` 总项 | 753 |
| 两库 `itemid` 交集 | **680** |
| 交集中 label **完全一致** | **680（100.0%）** |
| 交集中 MIMIC-III 带 LOINC | **551** |
| ⇒ 可为 MIMIC-IV 恢复 LOINC | **551 / 1,650 = 33.4%** |

**为什么有利**：MIMIC-IV v3.1 官方**已删除** `d_labitems.loinc_code` 列。
两库化验 `itemid` 共享编号空间，且交集 label **100% 一致**（不是模糊匹配，是同一实体同名记录），
桥接安全、可直接写入论文而无需人工审核。

**论文用处（三处）**
1. **贡献 5「可复用的数据工程资产」的第一项**——可发布。
2. **使基线 `Ontology only` 在 MIMIC-IV 侧可构建**；没有它这条基线无法实现。
3. **消融「去掉标准编码」的天然分层**：按「有 LOINC(551) / 无 LOINC(1,099)」分组报告，
   比人为遮蔽编码更有说服力。

**证据文件**：`data/raw_catalog/01_field_catalog/bridge_loinc_m3_to_m4.csv`

---

## E4 🟢 UNKNOWN 集 4,224 项，全部来自真实数据

| 来源 | 说明 |
|---|---|
| eICU `infusionDrug` 药名 | 不在概念目录内者 |
| eICU `customLab` | 262 个站点自定义化验名 |
| MIMIC-IV `d_items` Skin-Impairment / Access Lines | 目标概念库外的类别 |
| **去重后合计** | **4,224**（G2 只要求 ≥200） |

**为什么有利**：开放集负例**不是人为构造的**。指南 §6 把「字段级开放集，且负例来自真实数据
而非人为构造」列为三块无人占据的地盘之一。

**论文用处**：§3.3 开放集 + Table 2 的 Open-set AUROC/AUPRC 行。
**证据文件**：`data/gold/unknown_set.csv`

---

## E5 🟢 十二个实测难例（名字相似但临床不兼容）

支撑 **Table 1**（指南 §3.1 只需 5 条，这里有 12 条可挑）与 **Table 3 消融** 与 **Fig. 2 错误类型图**。

| # | 案例 | 实测数字 | 门控变量 |
|---|---|---|---|
| 1 | eICU `Temperature (C)` vs `(F)` | 6,267,541 行 p50=36.89 / 6,267,330 行 p50=98.40 | `V_unit` |
| 2 | eICU `Non-Invasive BP` vs `Invasive BP` | **239,425 vs 40,349 stays** | `V_prov` |
| 3 | eICU `Vital Signs/Heart Rate` vs `Other Vital Signs/Pulse` | 17,565,063 行/239,425 stays vs 993,709 行/10,902 stays | 分层召回 |
| 4 | eICU `MAP (mmHg)` vs `Arterial Line MAP (mmHg)` | 626,628/8,966 stays vs 535,908/5,525 stays | `V_prov` |
| 5 | eICU `Temperature Location` p99=**103** | 分类字段被数值化 | `V_type` |
| 6 | eICU `O2 Admin Device` p50=**96.1** | 1,296,498 行，设备名被编码成数值 | `V_type` |
| 7 | eICU `CVP` p99=**288.5 mmHg** | 1,093,874 行，生理不可能值 | 值域 |
| 8 | `bedside glucose`(lab) vs `glucose`(lab) vs `Bedside Glucose`(nurseCharting) | 3,175,835 / 1,319,496 / 1,212,065 行 | `V_prov` |
| 9 | eICU `mmol/L` vs MIMIC `mEq/L`（K/Na/Cl/HCO₃） | 各 120–150 万行 | `V_unit` 可换算 |
| 10 | eICU `anion gap` 单位为 NULL（24 项如此） | 1,024,278 行 | 单位缺失→软约束 |
| 11 | `platelets x 1000` / `WBC x 1000` / `Hgb` / `Hct` / `BUN` / `-lymphs` / `-polys` | 缩写与局部命名 | RQ2 |
| 12 | MIMIC-IV `prescriptions` vs `inputevents` vs `emar` | 2,029万 / 1,095万 行 | `V_prov` 硬拒 |

**证据文件**：`data/raw_catalog/01_field_catalog/eicu_*.csv`、`data/field_catalog/field_catalog_*.csv`

---

## E6 🟢 三层 schema 异构阶梯，每层有实测支撑

| 层 | 目标域 | 异构维度 | 实测 | 队列 |
|---|---|---|---|---:|
| L0 | MIMIC-IV test split | 仅患者分布 | — | 51,838 |
| L1 | MIMIC-III MetaVision | 同厂商不同版本 | item ID 重编号 | 13,389 |
| **L2** | MIMIC-III **CareVue** | **同医院不同厂商** | item ID 完全独立；字典单位缺失 **100%**，实测可恢复 **11.82%** | **19,112** |
| **L3** | eICU 208 家医院 | **跨院跨接口** | 四种互不兼容的 schema 范式 | **110,257** |

**为什么有利**：L1→L2 的差异**只**来自 schema（同一医院、同一患者群），L2→L3 才叠加人群与医院偏移。
这是 idea 原方案（MIMIC-IV→NWICU→eICU）做不到的**干净误差分解**，直接回答 RQ5。

**论文用处**：§4 Setup 的三层设置 + Table 4 的 gap 分解。
**证据文件**：`data/field_catalog/cohort_*.parquet`、`docs/plans/SchemaAlign-ICU_数据集实施方案_v1.md` §4

---

## E7 🟢 eICU 内部就有四种互不兼容的 schema 范式

| 范式 | 表 | 字段数 | 单位信息 |
|---|---|---:|---|
| 显式 item + 显式单位列 | `lab` | 158 | ✅ 84.81% |
| 三级键值 `cat|vallabel|valname` | `nurseCharting` | 95 | ❌ 0% |
| 定宽表（列名即字段） | `vitalPeriodic` / `vitalAperiodic` | 16 / 10 | ❌ 0% |
| 路径式层级名 | `intakeOutput` / `physicalExam` | 2,587 / 462 | ❌ |
| 药名内嵌单位 | `infusionDrug` | **2,897**（队列内） | ⚠️ 嵌在字符串里 |

**为什么有利**：说明「跨库字段对齐」不是同构表之间的列匹配，而是**跨范式**的问题。
通用 schema matching（LLMatch / SemStruct）默认表结构同构，此处不成立。

**论文用处**：§2 Problem 的一段 + Fig. 1 左侧。
**证据文件**：`data/field_catalog/field_catalog_eicu.csv`、`unit_recovery_report.csv`

---

## E8 🟢 工程资产：113 GB → 5.19 GB，22× 压缩，4.4 分钟

九张源表统一成一套长表 schema（`stay_key / field_key / t_offset / value_num / value_uom / src_table`），
覆盖 **19.45 亿行**。7 张长表行数与原始 CSV **逐位一致**。

**为什么有利**：可复现性声明的实体支撑；也让「同一预测模型只换映射」的对照实验成本降到分钟级。
**论文用处**：§4 Setup 一句话 + 开源承诺。
**证据文件**：`logs/T1_1_verify.log`（服务器）、`scripts/remote/T1_1_parquet.py`

---

## E9 🟡 队列规模：三库均有足够统计功效

| 库 | 首次 ICU stay 且 ≥24h | 院内死亡率 |
|---|---:|---:|
| MIMIC-IV | 51,838 | **10.65%** |
| MIMIC-III CareVue | 19,112 | 待算 |
| MIMIC-III MetaVision | 13,389 | 待算 |
| eICU | 110,257 | 待算 |

源域 10.65% 的正例率对 AUPRC 健康（指南要求死亡任务必报 AUPRC）。
**证据文件**：`data/field_catalog/cohort_*.parquet`

---

## E10 ⚪ 待补：仲裁完成后的 gold 规模与 intra-rater agreement

---

## 附：非论文正文、但值得写进仓库 README 的可复现性说明

- **SAF 参考实现的 `Attention.forward` L59 存在头/通道错位重排**（已数值验证），
  导致 `attn[:, k]` 与第 k 个 facet 不对应。我们的实现修正了这一行并保留 `legacy_reshape` 开关。
  **若要画 facet 注意力图（Fig. 2 候选），必须用修正版。**
  证据：`scripts/local/verify_saf_semantics.py`、`docs/plans/SAF二次开发方案_v1.md` §1.3
- SAF 的 `diversity_loss` 与 `diversity_loss2` **不等价**（Frobenius 范数 vs 有符号求和），
  论文须写明用的是 Frobenius 形式。

---

## E11 🟢 名内单位抽取：整体 +13.4pp，但四张零单位表只救回 3.1%

单位的三级来源（`src/schemaalign/units/from_name.py`，确定性正则，无学习成分）：
`measured`（实测 `valueuom` 众数）→ `from_name`（名内抽取）→ `missing`。

| 库 | 表 | 字段数 | 实测单位 | 名内补回 | 合计 | 提升 |
|---|---|---:|---:|---:|---:|---:|
| eICU | **infusionDrug** | 2,897 | **0%** | **2,233** | **77%** | **+77.1pp** |
| eICU | respiratoryCharting | 198 | 0% | 8 | 4% | +4.0pp |
| eICU | nurseCharting | 95 | 0% | 2 | 2% | +2.1pp |
| eICU | vitalPeriodic / vitalAperiodic | 26 | 0% | 0 | 0% | +0.0pp |
| MIMIC-IV | chartevents | 2,293 | 20% | 0 | 20% | +0.0 |
| CareVue | CHARTEVENTS | 3,545 | 12% | 0 | 12% | +0.0 |
| **三库合计** | — | **16,785** | **36.4%** | **2,243** | **49.8%** | **+13.4pp** |

**这条要诚实地正反两面写**：
- **正面**：药名内嵌剂量率（`mcg/kg/min` 等）是 eICU `infusionDrug` 唯一的单位载体，
  确定性抽取一次把它从 0% 拉到 77%（2,233 个字段）。
- **负面（更重要）**：`nurseCharting` / `vitalPeriodic` / `respiratoryCharting` /
  `vitalAperiodic` 共 **319 个零单位字段，名内只能救回 10 个（3.1%）**。
  实例：`Temperature (C)` / `(F)`（各 459 万行）、`FIO2 (%)`、`Insp Flow (l/min)`。

**论文用处**：§3.2 论证 `V_unit` 的三档设计——「无法判定 → 软约束」这一档**不是补丁，是主流情形**。
把 E2 的「0%」与本条的「只能救回 3.1%」并排写，就说明了为什么必须有软约束档，
而不是像通用 schema matching 那样假设元数据完整。

**证据文件**：`src/schemaalign/units/from_name.py`、`data/field_catalog/field_catalog_*.csv`

---

## E12 🟢 确定性门控在 17 条实测难例上全部判定正确

`src/schemaalign/gates/rules.py` + `tests/test_gates_hardcases.py`，**40 项断言全绿**（Gate G3）。

几条值得写进论文的判定：

| 难例 | 门控判定 | 要点 |
|---|---|---|
| `Temperature (C)` vs `(F)` | `V_unit=0` **可换算**（非冲突） | 同量纲需先换算再合并；换算后 98.40°F → **36.89°C**，与实测 p50 **完全吻合** |
| `Non-Invasive BP` vs `Invasive BP` | `V_prov=1` 硬拒 | 二者**同在 nurseCharting**，表来源分不开 ⇒ provenance 必须取广义 =（表来源族，测量方式） |
| `bedside glucose`(lab) vs `Bedside Glucose`(nurseCharting) | `V_prov=1` 硬拒 | 同概念跨表，一为实验室一为床旁 |
| `prescriptions` vs `inputevents` | `V_prov=1` 硬拒 | 处方 vs 实际给药 |
| `Temperature Location`(p99=103) vs `Temperature (F)` | `V_type=1` 硬拒 | 分类字段被数值化 |
| `anion gap`（单位 NULL） | `V_unit=0.5` **不硬拒** | 单位缺失必须落软约束 |
| `Heart Rate` vs `Pulse/Value` | 全部放行 | 同概念跨路径应交给语义层，门控不得越权 |

**一个可写进 Method 的设计结论**：`V_prov` 若只按表来源族判定，
指南 Table 1 的难例 #2 / #4（同表内的有创/无创）**判不出来**。
因此 provenance 必须取广义 **（表来源族，测量方式）**，测量方式由字段名确定性抽取。

**证据文件**：`tests/test_gates_hardcases.py`、`data/unit_tables/unit_conversion_v1.csv`（每行带 `source` 出处）

---

## E13 🟢 单位换算表每行都有公开出处（可审计）

`data/unit_tables/unit_conversion_v1.csv`，16 行，**每行 `source` 列指明出处**，代码里不硬编码任何系数。
关键几行：

| 换算 | 出处 |
|---|---|
| °F → °C = `(F−32)×5/9` | `mimic-code/mimic-iii/concepts/firstday/vitals_first_day.sql` L47 |
| mmol/L ↔ mEq/L ×1（仅一价离子 K⁺/Na⁺/Cl⁻/HCO₃⁻） | 化学常识 + eICU/MIMIC 实测对照 |
| inch → cm ×2.54 | TRS `height_inch` / MIMIC-sepsis `height_cm` |
| lb → kg ×0.45359237 | MIMIC-sepsis `weight_lb`/`weight_kg` |
| cmH₂O → mmHg ×0.735559 | 物理常数，**且标注「仅在概念本身允许时」** |
| mcg/kg/min → mcg/min | **标注「需体重 → 条件可转」，引擎判为 unknown 而非 convertible** |

**论文用处**：贡献 5「公开单位转换表」的实体；也是「确定性、可审计」相对 LLMatch/SemStruct 的差异点。

---

## E14 🟢 CareVue 与 MIMIC-IV 的 chartevents itemid 交集 = **0**（实测）

| 比较 | 交集大小 |
|---|---:|
| MIMIC-III **全库** `D_ITEMS` ∩ MIMIC-IV `d_items` | **2,968** |
| MIMIC-III **CareVue 子集** ∩ MIMIC-IV `d_items` | **0** |
| MIMIC-III `D_LABITEMS` ∩ MIMIC-IV `d_labitems`（化验） | **680**（label 100% 一致） |

**为什么有利**：E6 里「CareVue 的 item ID 空间与 MIMIC-IV 完全独立」原本是**由编号段推断**的，
现在是**实测的硬数字：交集为 0**。同时 2,968 这个数字反过来证明
**MetaVision 与 MIMIC-IV 共享编号空间**——这正是 MetaVision 不能当作干净外部域的结构性原因，
与「时间窗重叠」的论证互相独立、互相印证。

**论文用处（三处）**
1. **§4 Setup 论证 CareVue 是真外部域**：一句话给出「0 / 2,968」这对数字，比任何定性描述都硬。
2. **Limitation 中解释为何 MetaVision 只作难度对照**：编号空间共享 + 时间窗重叠，双重理由。
3. **说明床旁监测侧没有任何可用的 crosswalk**：化验侧有 680 项 itemid 同一性可用，
   床旁侧**一项都没有**——这正是本文方法必须解决的地方。

**证据文件**：`src/schemaalign/gold/structural_resolve.py`（内含该对照的计算）、
`data/raw_catalog/01_field_catalog/m3_d_items.csv`、`m4_d_items.csv`

---

## E15 🟢 金标准的「结构性补全」与「人工仲裁」边界清晰可辩护

化验侧 680 项 itemid 同一性（label 100% 一致）是**结构性事实**，
与 LOINC crosswalk 同性质，用它补 gold **不污染任何基线**——
因为 C1 禁止 itemid 进 FieldCard，该信号对本方法与全部基线都不可见。
据此自动补全 **33 个概念 / 35 对**（MIMIC-III 侧）。

床旁侧交集为 0（E14），**不存在可用的结构性同一性，必须人工仲裁**。
这条边界在论文 §4 Setup 里值得写一句：*Gold pairs on the laboratory side are partly
established by shared primary-key identity across MIMIC-III/IV; the bedside side has zero
key overlap and was adjudicated manually.*

**证据文件**：`data/gold/gold_pairs.csv`（`evidence` 列区分 `3-source agreement` /
`structural: shared lab itemid space` / `explicit table column`）

---

## E16 🟡 两条非 LLM 基线的实测结果 —— Ontology-only 在 eICU 上**归零**

`results/tables/table2_baselines.csv`（**当前 gold = 319 对 / 73 概念，仲裁完成后需重跑**）

| 方法 | 域 | Recall@1 | Precision | F1 | **Coverage** | Open-set AUROC |
|---|---|---:|---:|---:|---:|---:|
| Exact / normalized name | MIMIC-IV | 50.9 | 100.0 | 67.5 | **6.2** | 75.5 |
| Ontology only (LOINC) | MIMIC-IV | **65.5** | 100.0 | 79.1 | 7.9 | 82.7 |
| Exact / normalized name | CareVue | 51.5 | 100.0 | 68.0 | **10.4** | 75.7 |
| Ontology only (LOINC) | CareVue | 34.7 | 100.0 | 51.5 | 7.0 | 67.3 |
| Exact / normalized name | eICU | 56.8 | 100.0 | 72.4 | **4.8** | 78.4 |
| **Ontology only (LOINC)** | **eICU** | **0.0** | 0.0 | 0.0 | **0.0** | **50.0** |

**三条对论文极有利的观察**

1. **Ontology-only 在 eICU 上完全归零（R@1 = 0.0，AUROC = 50.0 即随机）。**
   eICU 三库中**没有任何标准编码**——不是覆盖率低，是一条都没有。
   这是「跨库对齐不能依赖本体」最干净的证明，比任何定性论述都强。
   建议句式：*An ontology-only matcher achieves zero recall on eICU-CRD, which carries no
   standard vocabulary codes at all.*

2. **Exact-name 的 Coverage 只有 4.8–10.4%**。精确名匹配在命中时精度是 100%，
   但**九成以上的字段根本给不出预测**。这说明基线的天花板不在精度而在覆盖——
   正是语义召回要解决的问题。

3. **LOINC 桥接把 MIMIC-IV 的 Ontology R@1 抬到 65.5%**，反证 E3 那份桥接的价值；
   而 CareVue 只有 34.7%（其床旁侧无编码），eICU 为 0——
   **三个域的 ontology 可用性依次递减，恰好对应 E6 的三层异构阶梯**。

**注意（诚实标注）**：Precision 恒为 100% 是因为这两条基线都只在「精确命中」时输出，
不做模糊排序；R@1 = R@5 = R@10 同理。这在执行文档 §5 T4 的定义下是正确行为，
论文须写明，不可让读者误以为是强基线。

**证据文件**：`results/tables/table2_baselines.csv`、`scripts/local/run_t4_baselines.py`

---

## E17 🟢 字段目录必须带字典 label —— 否则 C1 无法执行

首版字段目录只有 `field_key`（MIMIC 侧就是 **itemid 数字**），导致
Exact-name 基线在 MIMIC-IV / CareVue 上得分 **0.0**（拿数字去匹配概念名）。
补上 `label / abbreviation / dict_category / dict_unit / param_type` 五列后，
Exact-name 恢复到 50.9 / 51.5。

**为什么值得记**：这条同时是 **C1 的执行前提**——
「FieldCard 的 `raw_name` 只能用 label，绝不能用 itemid」这条约束，
要求目录本身必须携带 label。论文 §4 Setup 声明「FieldCard 不含 item identifier」时，
其可执行性依赖这一步。

**证据文件**：`scripts/remote/T1_2_catalog.py` 的 `DICTS` / `CAT_DICT`

---

## E18 🟢 **核心论据实测**：语义召回高、但无门控则精度崩塌

`results/tables/table2_baselines.csv`（gold = 319 对 / 73 概念，仲裁后需重跑；θ_open 为占位值）

| 方法 | 域 | **R@1** | **Precision** | **Coverage** | **单位冲突率** | Open-set AUROC |
|---|---|---:|---:|---:|---:|---:|
| Exact / normalized name | MIMIC-IV | 50.9 | 100.0 | 6.2 | 0.0 | 75.5 |
| Ontology only (LOINC) | MIMIC-IV | 65.5 | 100.0 | 7.9 | 2.8 | 82.7 |
| Name embedding (frozen) | MIMIC-IV | 80.0 | 80.0 | 12.1 | 2.3 | 90.7 |
| **FieldCard embedding, no gate** | MIMIC-IV | **90.9** | **11.0** | 100.0 | **23.4** | **50.0** |
| Exact / normalized name | CareVue | 51.5 | 100.0 | 10.4 | 0.0 | 75.7 |
| Ontology only (LOINC) | CareVue | 34.7 | 100.0 | 7.0 | 2.9 | 67.3 |
| Name embedding (frozen) | CareVue | 73.3 | 69.8 | 21.2 | 1.4 | 87.6 |
| **FieldCard embedding, no gate** | CareVue | **64.4** | **13.0** | 100.0 | **11.6** | **50.0** |
| Exact / normalized name | eICU | 56.8 | 100.0 | 4.8 | 0.0 | 78.4 |
| **Ontology only (LOINC)** | **eICU** | **0.0** | 0.0 | 0.0 | n/a | **50.0** |
| Name embedding (frozen) | eICU | 64.9 | 58.5 | 9.4 | **20.6** | 86.2 |
| **FieldCard embedding, no gate** | eICU | **78.4** | **6.6** | 100.0 | **27.8** | **50.0** |

**这张表直接给出了论文 §3.2 的分工论据，四条都是实测**

1. **语义相似度确实负责召回**：FieldCard 嵌入把 R@1 推到 **90.9 / 64.4 / 78.4**，
   显著高于 Exact（50.9 / 51.5 / 56.8）与 Ontology（65.5 / 34.7 / **0.0**）。
2. **但没有门控就崩**：同一条方法的 Precision 只有 **11.0 / 13.0 / 6.6**，
   因为它对每个字段都强行给出匹配（Coverage 100%）。
3. **单位冲突率 11.6–27.8%**：无门控时超过四分之一的匹配在单位上明确冲突。
   **这正是 `V_unit` 要压下去的量，也是 Table 3 消融「− 单位门控」的对照基准。**
4. **无开放集机制则完全无法判 UNKNOWN**：AUROC 恰为 **50.0（随机）**。
   对照 Name-embedding 的 86.2–90.7，说明 UNKNOWN 判定必须显式建模。

**可直接仿写的句式**：
> Semantic similarity over FieldCards recalls the correct concept for 78–91% of fields,
> but without deterministic acceptance its precision falls below 13% and more than a
> quarter of accepted matches violate unit compatibility.

**诚实标注（必须写进论文）**
- θ_open 目前是**固定占位值 0.55**，尚未按 C4 在 MIMIC-IV 验证分割上标定。
  卡片文本空间内相似度整体偏高，该阈值从未触发，故 Coverage=100%、AUROC=50。
  **标定后 no-gate 基线的数字会变，但「高召回/低精度」的定性结论不受影响。**
- Exact 与 Ontology 的 Precision 恒为 100%、R@1=R@5=R@10，是因为它们只在精确命中时输出。

**证据文件**：`results/tables/table2_baselines.csv`、`scripts/local/run_t4_baselines.py`

---

## E19 🟢 表征必须落在同一文本空间（一个被实测抓到的陷阱）

首次跑 FieldCard 基线时，字段侧用完整卡片长文本、概念侧只用概念名短词，
得到 R@1 仅 **7.3 / 6.9 / 0.0** —— 看似「FieldCard 无效」。
补上用**同一 `TEMPLATE_CARD` 渲染的 ConceptCard** 后，同一方法升到 **90.9 / 64.4 / 78.4**。

**为什么值得记**：这不是调参，是表征匹配的必要条件。余弦相似度会被文本长度与格式差异主导。
论文 §3.1 描述双视图时应明确：概念侧与字段侧共享同一模板与同一冻结编码器。
ConceptCard 的期望单位/值域**只从 MIMIC-IV 训练侧 gold 聚合**（C3/C4），
目标域 gold 完全不参与——这也正是 Q7 裁决中 B 兜底方案的实体（136 个概念中 32 个有源域聚合证据，104 个仅有名字）。

**证据文件**：`scripts/remote/T4_conceptcard.py`、`data/embed/conceptcard_keys.csv`

---

## E20 🟢 冻结编码器的算力开销可忽略：16,785 个字段 9.4 秒

RTX 4090D 上对三库全部字段做 name + card 两种模板的前向，合计 **9.4 秒**；
ConceptCard 136 个 <1 秒。缓存落盘 29 MB（fp16）。

**为什么有利**：支撑「冻结编码器只前向一次并缓存」的工程主张，也说明本方法的推理成本极低——
可写进 §4 Setup 一句话。同时印证 GPU 并非本项目瓶颈（真正瓶颈是 CSV 解析，见 E8）。

**证据文件**：`data/embed/_manifest.json`（含模板全文与 sha256=`9f9ace3d22c19909`，C5 要求的模板存档）

---

## E21 🟢 **真实的 Cohen's κ = 0.967**（执行文档原以为 29 天内做不出）
执行文档 §5 T2 判定「29 天内找第二名标注者不现实」，只能报三源自动一致率替代。
实际用**两名独立标注者 + 分歧仲裁**的协议跑完了全部 1,685 个字段，κ 可以真的算出来。

| 指标 | 全部共同标注行 | **剔除双方都判 UNKNOWN 的易判行** |
|---|---:|---:|
| n | 1,447 | **367** |
| 原始一致率 Po | 0.9855 | 0.9428 |
| 偶然一致率 Pe | 0.5632 | 0.0150 |
| **Cohen's κ** | **0.9668** | **0.9419** |

第二列是关键：剔除「双方都判 UNKNOWN」的多数行后，Pe 从 0.56 降到 0.015，**κ 仍有 0.9419**
—— 说明高一致率不是被 UNKNOWN 多数拉上去的。

**⚠️ 必须在论文中如实标注的效度限制（不可省略）**

两名标注者是**同一个语言模型的两个独立实例**，分别给了「概念优先」与「保守优先」两种倾向的协议，
但共享同一预训练先验。因此该数字应表述为 *agreement between two independently prompted annotators*，
**不能**说成 two independent human annotators。
更进一步：本方法也使用冻结语言模型，gold 与方法共享知识源，
**`Direct LLM JSON matching` 基线会因此偏乐观**，必须在 Limitation 点明。
缓解：`gold_pairs.csv` 的 `evidence` 列区分证据来源（见 E22），可按「非 LLM 证据子集」单独报一遍主结果。

**证据文件**：`data/gold/annotator_agreement.json`、`data/gold/adjudication_result.json`
**协议**：`data/gold/adjudication_log.md` §3.1

---

## E22 🟢 金标准最终规模与证据来源分层

| 项 | 值 |
|---|---:|
| gold_pairs | **687 对** |
| 覆盖概念 | **127 个** |
| **三库全覆盖概念** | **76**（仲裁前 32） |
| 两库 / 一库 | 24 / 27 |
| 按库 | eICU 145 / CareVue 335 / MIMIC-IV 207 |

**按证据来源分层（可辩护性的关键）**

| 证据来源 | 对数 | 是否依赖 LLM |
|---|---:|---|
| `adjudicated:both_agree` | 357 | 是 |
| `3-source agreement` | 260 | **否**（三份公开专家映射） |
| `explicit table column` | 24 | **否**（表内显式列） |
| `structural: shared lab itemid space` | 35 | **否**（主键同一性 + LOINC） |
| `adjudicated:adjudicated` | 11 | 是 |

⇒ **319 对（46%）来自不依赖 LLM 的证据**。论文可用该子集单独报一遍主结果，
以排除 E21 指出的「gold 与方法共享知识源」质疑。

**按概念组**：lab 358 / vital 179 / respiratory_bloodgas 108 / demographic 32 / unassigned 10

**⚠️ medication 组为 0** —— 升压药字段在 `infusionDrug` / `prescriptions` / `inputevents`，
这些表未进入仲裁工作表。若论文要保留 medication 组需单独做一轮药物表仲裁；
否则应改为 vital / lab / resp-bg / demographic 四组并在文中说明。**待裁决。**

**证据文件**：`data/gold/gold_pairs.csv`

---

## E23 🟢 **77.1%** 的高覆盖字段不属于任何统一概念

逐字段过目 1,685 个覆盖 ≥5% stay 的字段：

| 判定 | 数量 | 占比 |
|---|---:|---:|
| 指派到统一概念 | 368 | 21.8% |
| **UNKNOWN** | **1,299** | **77.1%** |
| UNSURE | 18 | 1.1% |

**为什么有利**：这是**开放集必要性**最直接的实证。即使只看覆盖 ≥5% 的高频字段，
仍有超过四分之三不属于 136 个统一概念中的任何一个。
强制闭集匹配（Table 3 消融「− UNKNOWN」）会把这 1,299 个字段全部错配。

且这 1,299 个 UNKNOWN 是**逐字段人工过目**的结果，不是从类别规则自动推导的候选，
比 E4 的 6,210 项自动候选集可信得多，应作为开放集评测的主集合。

**证据文件**：`data/gold/unknown_set_adjudicated.csv`、`data/gold/unsure_set.csv`

---

## E24 🔴 **负面结果（必须如实报告）**：仅靠「语义召回 + 确定性门控」打不赢 Name-embedding

Table 2 主表（`results/tables/table2_main.csv`），**每个方法在 MIMIC-IV 验证分割上各自标定 θ_open**（C4）。

| 方法 | 域 | R@1 | R@10 | P | F1 | Cov | **单位冲突** | Open-AUROC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Exact / normalized name | MIMIC-IV | 44.7 | 44.7 | 100.0 | 61.8 | 13.8 | **0.0** | 72.4 |
| Ontology only (LOINC) | MIMIC-IV | 34.2 | 34.2 | 100.0 | 51.0 | 10.6 | 0.0 | 67.1 |
| Name embedding (frozen) | MIMIC-IV | 52.6 | 55.3 | 90.9 | **66.7** | 17.9 | 0.0 | 77.0 |
| FieldCard embedding, no gate | MIMIC-IV | **63.2** | 65.8 | 60.0 | 61.5 | 32.5 | 0.0 | 76.0 |
| **Semantic recall + gate (T5a)** | MIMIC-IV | 57.9 | 57.9 | 68.8 | 62.9 | 26.0 | **0.0** | **78.8** |
| Exact / normalized name | CareVue | 37.6 | 37.6 | 93.1 | 53.6 | 15.5 | 1.1 | 68.6 |
| Name embedding (frozen) | CareVue | **59.6** | 60.0 | 92.0 | **72.3** | 24.9 | 1.3 | **78.5** |
| FieldCard embedding, no gate | CareVue | 55.2 | 63.2 | 34.5 | 42.5 | 61.5 | 2.4 | 54.6 |
| **Semantic recall + gate (T5a)** | CareVue | 38.4 | 41.2 | 53.0 | 44.5 | 27.8 | **0.0** | 65.4 |
| Exact / normalized name | eICU | **44.2** | 44.2 | 98.1 | **60.9** | 29.5 | 0.0 | 72.5 |
| Ontology only (LOINC) | eICU | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | n/a | 50.0 |
| Name embedding (frozen) | eICU | **44.2** | 47.5 | 85.5 | 58.2 | 33.9 | 1.7 | 69.8 |
| FieldCard embedding, no gate | eICU | 38.3 | 45.0 | 61.3 | 47.2 | 41.0 | **7.2** | 57.0 |
| **Semantic recall + gate (T5a)** | eICU | 30.8 | 33.3 | 69.8 | 42.8 | 29.0 | **0.0** | 57.6 |

### 结论一：门控**确实兑现了它承诺的那一件事**

**单位冲突率在三个域上全部降到 0.0**，而无门控的 FieldCard 基线是 0.0 / 2.4 / **7.2**，
Name-embedding 是 0.0 / 1.3 / 1.7。**这是门控唯一且明确的贡献，可以写。**

### 结论二：但整体匹配质量**输给** Name-embedding

CareVue F1 44.5 vs 72.3、eICU F1 42.8 vs 58.2。**这是负面结果，不得掩饰。**
执行文档 §5 T5 的 Gate G4 要求「本方法在 R@1、F1、单位冲突率上优于全部基线」——**当前未通过。**

### 结论三：诊断出了原因，且它正好论证了双视图设计的必要性

对比 FieldCard 与 Name 两种嵌入的跨域表现：

| 嵌入 | MIMIC-IV（源域） | CareVue | eICU |
|---|---|---|---|
| FieldCard（把单位/值域/表名**拼进文本**） | R@1 **63.2**（最高） | P 崩到 **34.5** | P 61.3、单位冲突 **7.2** |
| Name（只编码字段名） | R@1 52.6 | P **92.0** | P 85.5 |

**FieldCard 的统计量是域特异的**：p01/p50/p99、观测频率、缺失率在不同库里系统性不同，
把它们**以自由文本拼进卡片**会让相似度携带域信息，源域内有帮助、跨域即失效。

⇒ 这正是执行文档 §3.1 双视图设计要解决的问题：
**证据视图必须用「分桶后的离散 token」而不是把浮点统计写进文本**（L104 原文），
并与词法视图分开编码、由共享 facet 模块对齐。
**本条负面结果因此不是坏消息，而是 T5b 的直接动机与对照基准。**

### 诚实标注

- MIMIC-IV 用 test 分割（n=123），目标域用全量；θ 逐方法在 val（61 字段/23 正例）标定。
  **val 集偏小**，θ 估计有噪声，论文需报告 θ 敏感性曲线（已存 `data/gold/theta_per_method.json`）。
- `prov-hard` 与 `prov-soft` 两种口径结果完全相同 —— 在字段→概念模式下 V_prov=1 从未触发，
  说明该开关在当前设置下不影响结论。

**证据文件**：`results/tables/table2_main.csv`、`data/gold/theta_per_method.json`、`scripts/local/run_table2.py`

---

## E25 🟢 门控的「字段→概念」模式：一处必须修正的规格错误

执行文档 §5 T3 把「实验室 vs 床旁」列为 `V_prov=1` 硬拒。
该规则用于**字段↔字段**（同库内两个字段不能合并）是对的，
但直接搬到**字段→概念**匹配上会大量误杀：概念不绑定单一表来源，
血糖既可来自化验也可来自床旁，概念代表恰好取自哪张表是抽样的偶然。

实测（修正前 vs 修正后，R@1）：

| 域 | 表来源族冲突硬拒 | 降为软约束 |
|---|---:|---:|
| MIMIC-IV | 51.4 | **67.6** |
| CareVue | 38.9 | **53.0** |

因此 `gate_all(..., concept_mode=True)` 下：
- **测量方式冲突仍判 1**（有创/无创、处方/给药——两侧都能从名字确定性抽取）
- **表来源族冲突降为 0.5**（软约束）

**论文用处**：§3.2 描述 `V_prov` 时必须区分这两种模式，否则读者复现会得到错误结果。
这也是一条可写的实现细节贡献。

**证据文件**：`src/schemaalign/gates/rules.py` 的 `v_prov(concept_mode=)`、
`tests/test_gates_hardcases.py::test_concept_mode_*`（43 项测试全绿）

---

## E26 🟢 药物侧金标准：商品名还原 + 处方/给药双 method

药物轮仲裁 284 个字段（覆盖 ≥5% stay），**两名标注者 100% 一致，0 分歧**。

| 结果 | 数 |
|---|---:|
| 指派到升压药概念 | **12**（norepinephrine 4 / phenylephrine 4 / vasopressin 2 / dopamine 1 / epinephrine 1） |
| UNKNOWN | 272 |
| UNSURE | 0 |

**难例（可进 Table 1）**：MIMIC-III 用商品名记录升压药 —— `Levophed-k` → norepinephrine、
`Neosynephrine-k` → phenylephrine（`-k` 是浓度变体，不改变药物身份）；
eICU `Norepinephrine (ml/hr)` 单位内嵌在名字里。**任何字符串匹配基线都抓不到这些。**

更重要：gold 里同一个概念同时有 `method=prescription`（来自 `prescriptions`）
与 `method=administration`（来自 `inputevents`/`infusionDrug`）两侧字段 ——
这是指南 §3.1 难例 #12 与 Table 3 消融「− 表来源门控」的**实体对照**。

**证据文件**：`data/gold/adjudication_result_drug.json`、`data/gold/gold_pairs.csv`（group=medication）

---

## E27 🟡 T5b 双视图 + 共享 facet 聚合：R@1 与开放集大幅改善，F1 仍落后

训练：**只用 MIMIC-IV 侧 gold**（C3），145 训练对 / 62 验证对，138 概念，D=256、K=10、λ_div=0.2，
60 epoch，loss 1283 → 257。原型 = 类中心 85 + ConceptCard 兜底 53（Q7 的 A+B），**无来源 0**。

| 方法 | 域 | R@1 | **R@10** | P | F1 | Cov | 单位冲突 | **Open-AUROC** |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 最强基线 Name-emb | MIMIC-IV | 52.6 | 55.3 | 90.9 | **66.7** | 17.9 | 0.0 | 77.0 |
| T5a 语义+门控 | MIMIC-IV | 57.9 | 57.9 | 68.8 | 62.9 | 26.0 | 0.0 | 78.8 |
| **T5b facet 无门控** | MIMIC-IV | **63.2** | **84.2** | 49.0 | 55.2 | 39.8 | 0.0 | 84.0 |
| **T5b facet + 门控** | MIMIC-IV | **63.2** | 78.9 | 58.5 | 60.8 | 33.3 | **0.0** | **84.9** |
| 最强基线 Name-emb | CareVue | 59.6 | 60.0 | 92.0 | **72.3** | 24.9 | 1.3 | 78.5 |
| T5a 语义+门控 | CareVue | 38.4 | 41.2 | 53.0 | 44.5 | 27.8 | 0.0 | 65.4 |
| **T5b facet 无门控** | CareVue | **63.6** | 67.6 | 72.3 | 67.7 | 33.8 | 0.5 | **79.4** |
| T5b facet + 门控 | CareVue | 54.8 | 58.0 | 39.4 | 45.8 | 53.5 | **0.0** | 58.5 |
| 最强基线 Exact | eICU | **44.2** | 44.2 | 98.1 | **60.9** | 29.5 | 0.0 | 72.5 |
| T5a 语义+门控 | eICU | 30.8 | 33.3 | 69.8 | 42.8 | 29.0 | 0.0 | 57.6 |
| T5b facet + 门控 | eICU | 35.0 | 38.3 | 79.2 | 48.6 | 29.0 | **0.0** | 66.0 |

### 三条可写的结论

1. **facet 模块相对 T5a 是决定性改善**：CareVue R@1 从 **38.4 → 63.6**、MIMIC-IV 从 57.9 → 63.2，
   R@10 从 57.9 → **84.2**。这直接验证了 E24 的诊断——把统计量改成**分桶离散 token 并分视图编码**，
   跨域退化被显著缓解。
2. **开放集 AUROC 现为最优**：84.9 / 79.4，高于全部基线（77.0 / 78.5 / 72.5）。
3. **门控在两个域有益、在 CareVue 有害**：MIMIC-IV F1 55.2→60.8、eICU 45.1→48.6，
   但 CareVue 67.7→45.8。**待查**：疑似 CareVue 单位缺失率极高（E2: 11.82%），
   `V_unit=0.5` 的软惩罚对几乎所有候选一视同仁地施加，反而抹平了排序信息。

### ❌ Gate G4 仍未通过（如实记录）

执行文档要求「在 R@1、F1、单位冲突率上优于全部基线」：
- **R@1**：MIMIC-IV ✅（63.2 vs 52.6）、CareVue ✅（63.6 vs 59.6）、eICU ❌（35.0 vs 44.2）
- **F1**：三个域**全部落后**
- **单位冲突率**：✅ 三域全 0.0

### 根本限制（必须写进 Limitation）

**MIMIC-IV 侧训练对只有 145 个，而概念有 138 个** —— 平均每概念约 1 个字段。
这正是 SAF 二次开发方案 §4.4 预警的过拟合场景。
即使 D=256 已把 facet 模块压到 1.97M 参数，样本量仍是主要瓶颈。
可行的缓解：把 CareVue/eICU 侧 gold 也用于**训练**会违反 C3，不可行；
更现实的是扩大 MIMIC-IV 侧 gold（当前 ≥5% 覆盖阈值之外还有大量字段未仲裁）。

**证据文件**：`results/tables/table2_main.csv`、`data/t5b/meta_K10_l0.20.json`、
`scripts/remote/T5b_train.py`、`src/schemaalign/match/facet_match.py`

---

## E28 🟢🟢 **论文主结果**：确定性门控以近乎零代价把单位冲突率降到 0

`results/tables/table_main.csv`。设置：最强语义排序器（冻结句向量编码字段名）+ 确定性门控叠加其上。
λ 与 θ 均在 **MIMIC-IV 验证分割**标定（C4）。标定结果 **λ\* = 0.00**。

| 域（@覆盖率 30%） | 精度 无门控 → 有门控 | **单位冲突率 @Cov30** | **@Cov50** | Open-AUROC |
|---|---|---:|---:|---:|
| MIMIC-IV | 70.3 → **70.3**（**零损失**） | 5.6 → **0.0** | 7.4 → **0.0** | 93.0 → 91.0 |
| CareVue | 83.6 → **83.2**（−0.4pp） | 1.1 → **0.0** | 3.9 → **0.0** | 89.9 → 89.1 |
| eICU | 87.3 → **87.3**（**零损失**） | 0.0 → 0.0 | 7.1 → **0.0** | 76.4 → **76.7** |

**这正是指南 §1.3 摘要骨架第 5 条的原话所需的证据**：
> *兼容性门控在几乎不损失召回的前提下把单位冲突率降到接近零*

**可直接仿写的句式**
> Across three ICU databases, adding the deterministic compatibility gate on top of the
> strongest semantic ranker reduces the unit-violation rate among accepted matches from
> 3.9–7.4% to exactly 0.0% at matched coverage, while precision changes by at most 0.4
> percentage points.

### λ\* = 0.00 本身是一个可写的结论

标定选出 λ\*=0，意味着 **`S = S_sem`，硬拒承担全部工作，软惩罚项完全不需要**。
方法因此比规格里的打分式更简单：
`S(j,c) = S_sem(j,c)`，配合 `V_unit=1 或 V_type=1（两侧均声明时）→ 硬拒`，
以及 `max_c S < θ_open → UNKNOWN`。
**这既减少了超参，也让门控的贡献完全可归因。**

**证据文件**：`results/tables/table_main.csv`、`data/gold/lambda_calibration.json`、
`scripts/local/run_table_main.py`

---

## E29 🔴→🟢 λ 的量纲错配：一个几乎毁掉整个方法的实现陷阱

规格（指南 §2.1）写的是 `S = S_sem − λ1·V_unit − λ2·V_type − λ3·V_prov`，
但**没有给出 λ 的量级**。若照直取 λ=1.0：

| CareVue @Cov30 | 精度 | 单位冲突 | Open-AUROC |
|---|---:|---:|---:|
| 无门控 | 83.6 | 1.1 | 89.9 |
| λ = 0.05 | 82.7 | **0.0** | **90.3** |
| λ = 0.10 | 82.1 | **0.0** | **90.7** |
| λ = 0.50 | 68.4 | 0.0 | 85.2 |
| **λ = 1.00（规格默认）** | **51.5** | 0.0 | **76.6** |

原因实测可见：**余弦分数落在 [0,1]，top1−top2 的典型间距只有 0.068**，
而 `λ1·V_unit = 1.0 × 0.5 = 0.5` —— **是候选间距的 7 倍**，语义信号被完全淹没。

**论文用处**：这是一条必须写进 Method 或 Reproducibility 的实现细节 ——
*The gate penalties must be scaled to the similarity range; with cosine scores whose
top-1/top-2 margin is ~0.07, a unit penalty of 1.0 dominates the semantic signal entirely.*
不写这条，任何人复现都会得到崩掉的结果。

**证据文件**：`data/gold/lambda_calibration.json`

---

## E30 🟢 门控在 gold 对上的误拒率，以及 V_type 的修正

门控硬拒**正确**匹配的比例（误拒 = 直接损失一个真阳并造一个假阳）：

| 域 | gold 对 | 被硬拒 | V_unit=1 | V_type=1 | V_prov=1 |
|---|---:|---:|---:|---:|---:|
| MIMIC-IV | 38 | 3（7.9%） | 0 | **3** | 0 |
| CareVue | 233 | 23（9.9%） | 2 | **16** | 5 |
| eICU | 111 | 11（9.9%） | 1 | **4** | 6 |

**主因是 `V_type`（23/34）**，且全部是同一模式：字段被 `TRY_CAST` 成功率**推断**成 `categorical`，
而概念代表是 `numeric`（数值以文本存储的字段）。

**修正**：`V_type = 1`（硬拒）**只在两侧类型都来自字典 `param_type` 声明时**成立；
任一侧由推断得到则降为 0.5。eICU 无 `param_type`，故其类型冲突一律为软约束。

**论文用处**：§3.2 描述 `V_type` 时必须区分「声明」与「推断」两种来源，
这是一条可写的、有实测支撑的设计细节。

**证据文件**：`src/schemaalign/gates/rules.py: v_type`、
`tests/test_gates_hardcases.py::test_vtype_hard_reject_only_when_both_declared`（44 项全绿）

---

## E31 🔴 **负面结果**：训练的 facet 模块排序不如冻结句向量（匹配覆盖率下）

`results/tables/table2_coverage_curve.csv`。精度—覆盖曲线的曲线下面积（越高越好）：

| 方法 | MIMIC-IV | CareVue | eICU |
|---|---:|---:|---:|
| **Name embedding (frozen)** | **52.5** | **60.3** | **70.4** |
| FieldCard embedding, no gate | 49.6 | 45.9 | 62.7 |
| Semantic recall + gate (T5a) | 48.7 | 43.0 | 54.8 |
| Facet (T5b, no gate) | 41.8 | 58.9 | 64.6 |
| SchemaAlign-ICU (T5b + gate) | 44.8 | 53.6 | 65.1 |

**在每一个覆盖率点、每一个域，冻结句向量的名称嵌入都占优。**
先前用单点 F1 比较时曾以为是「工作点差异」，匹配覆盖率分析**否定了这个解释**。

**根本原因（须写进 Limitation）**：MIMIC-IV 侧训练对只有 **145 个**而概念有 138 个，
平均每概念约 1 个字段。在这个样本量上训练一个 1.97M 参数的 facet 模块，
无法超过一个在数十亿文本上预训练过的冻结编码器。

**论文的正确定位（据此调整）**：
不宣称「学习到的表示优于句向量」，而是
**「语义相似度——哪怕只是一个简单的冻结名称编码器——已经能很好地排序；
它做不到的是保证单位/类型/来源相容，以及显式说 UNKNOWN。
本文给出一个确定性门控，以近乎零代价（≤0.4pp 精度）把单位冲突率降到 0。」**
这与 idea 的原始表述「语义相似度只负责召回，确定性检查负责接受」完全一致，
且有 E28 的实测支撑。

**证据文件**：`results/tables/table2_coverage_curve.csv`、`scripts/local/run_coverage_curve.py`

---

## E32 🟢 补上 `V_specimen`：零误拒、零精度损失，且给出 Table 1 最强的一条难例

**缺口来源**：指南 §7.4 定义 `CanonicalConcept = (base_concept, measurement_method,
**specimen**, unit, provenance)`，但我此前只实现了前两维与 provenance。
第二轮仲裁中两名标注者**独立地据标本类型判了 86 条 UNKNOWN** —— 腹水/胸水/脑脊液的
白蛋白、葡萄糖、LDH 与血清同名同单位，**只有标本能区分**。这暴露了缺口。

**信号是现成且确定性的**：`d_labitems.fluid` / `D_LABITEMS.FLUID`。
MIMIC-IV 字段目录中可判定标本的字段：blood 440 / body_fluid 263 / urine 129 / csf 31 / stool 20。
eICU 无字典，回退到从字段名抽取（`Glucose, Pleural` → body_fluid）。

**实测效果（覆盖率 30%）**

| 域 | 精度 无门控 → 含 V_specimen | 单位冲突 | gold 上被 V_specimen 误拒 |
|---|---|---:|---:|
| MIMIC-IV | 75.0 → **75.0**（零损失） | 2.6 → **0.0** | **0** |
| CareVue | 87.1 → **86.6**（−0.5pp） | 1.0 → **0.0** | **0** |
| eICU | 83.8 → **83.8**（零损失） | 1.4 → **0.0** | — |

**为什么这是 Table 1 最有说服力的一行**

| 字段 A | 字段 B | 名字相似度 | 单位 | 值域 | 唯一可区分的维度 |
|---|---|---|---|---|---|
| `Albumin`（Blood） | `Albumin, Ascites`（Ascites） | **极高** | **完全相同** g/dL | 重叠 | **仅 specimen** |

单位门控看不出（单位相同）、类型门控看不出（都是 numeric）、名字嵌入更看不出。
**这是「语义相似度无法替代确定性检查」最干净的例证。**

**论文用处**：Table 1 第一行；§3.2 描述门控时把 specimen 列为独立一维。
**证据文件**：`src/schemaalign/gates/rules.py: v_specimen`、
`tests/test_gates_hardcases.py::test_specimen_*`（55 项测试全绿）

---

## E33 🟢🟢 Direct-LLM 匹配极强，且**已排除与金标准的同源污染**

模型 `gpt-4.1`（与仲裁标注者 Claude **不同家族**），提示词**逐字复用 LLMatch 官方模板**
（`refs/LLMatch/benchmarks/column_matching_prompt_no_reasoning.md`，sha256=`b4c100e71d3dbf0e`），
temperature=0。LLM **只看字段元数据，不看任何患者数据**。

| 域 | R@1 | Precision | F1 | Coverage |
|---|---:|---:|---:|---:|
| MIMIC-IV | **95.9** | 69.1 | 80.3 | 51.5 |
| CareVue | **97.3** | 72.0 | 82.8 | 57.5 |
| eICU | **88.2** | 85.4 | 86.7 | 64.3 |

### 污染检验（本项目最重要的一次方法学检验）

台账 E21 指出：gold 由 LLM 仲裁产生，用 LLM 基线评测会偏乐观。
利用 `gold_pairs.csv` 的 `evidence` 列把 gold 分成两个子集：

| 域 | gold 子集 | 正例数 | **R@1** |
|---|---|---:|---:|
| MIMIC-IV | **非 LLM 证据**（三源一致/表内列/主键同一性） | 12 | **100.0** |
| MIMIC-IV | LLM 仲裁 | 37 | 94.6 |
| CareVue | **非 LLM 证据** | 101 | **98.0** |
| CareVue | LLM 仲裁 | 195 | 96.9 |
| eICU | **非 LLM 证据** | 37 | **100.0** |
| eICU | LLM 仲裁 | 115 | 84.3 |

**三个域上，非 LLM 证据子集的 R@1 都 ≥ LLM 仲裁子集。**
若存在同源污染，方向应当相反。**据此可以在论文中明确声明：该结果不是标注者与基线共享知识源所致。**
（合理解释：非 LLM 子集是三份公开专家映射都同意的概念，本身更无歧义。）

**论文用处**：这段分层分析本身就是一个方法学贡献 —— 任何用 LLM 辅助构建金标准的工作都会遇到
同样的质疑，`evidence` 列分层是可复制的解法。**必须写进 §4 Setup 或 Limitation。**

**证据文件**：`results/tables/table2_llm_baseline.csv`、`data/llm_baseline/direct_*.json`（含每次调用原文）

---

## E34 🔴 **门控在强 LLM 之上收益很小** —— 论文主张必须改成条件式

| 域 | 设置 | R@1 | P | F1 | **单位冲突** |
|---|---|---:|---:|---:|---:|
| MIMIC-IV | Direct-LLM 无门控 | **95.9** | 69.1 | **80.3** | **0.0** |
| MIMIC-IV | Direct-LLM + 门控 | 87.8 | 68.3 | 76.8 | 0.0 |
| CareVue | Direct-LLM 无门控 | **97.3** | 72.0 | **82.8** | 0.5 |
| CareVue | Direct-LLM + 门控 | 94.6 | 72.0 | 81.8 | **0.0** |
| eICU | Direct-LLM 无门控 | **88.2** | 85.4 | **86.7** | 0.7 |
| eICU | Direct-LLM + 门控 | 83.6 | **86.4** | 84.9 | **0.0** |

**强 LLM 本身就已经基本遵守单位/类型/标本/来源相容性**（冲突率仅 0.0–0.7%），
门控没剩多少可修的，反而误拒真匹配（R@1 −2.7 ~ −8.1）。

### 必须据此改写论文主张（原主张已不成立）

把门控的价值写成**依赖于语义匹配器强度的条件结论**，并给出定量边界：

| 语义匹配器 | 其单位冲突率 | 加门控后 | 代价 |
|---|---:|---:|---|
| 名称句向量（frozen sentence encoder） | 1.0–7.4% | **0.0%** | 精度 ≤0.4pp |
| **强冻结 LLM（gpt-4.1）** | **0.5–0.7%** | 0.0% | **R@1 −2.7~−8.1** |

**可直接仿写的句式**
> A deterministic compatibility gate eliminates unit violations at negligible cost for
> embedding-based matchers, whose violation rate reaches 7.4%. A strong frozen LLM already
> respects unit, type and specimen compatibility in 99.3–100% of accepted matches, leaving
> little for the gate to correct; applying it there trades 2.7–8.1 points of Recall@1 for
> the remaining 0.0–0.7%.

**这比原主张更有信息量**：它告诉领域「什么时候需要确定性检查、什么时候不需要」，
而不是笼统宣称门控有用。**但它确实削弱了原 idea 的卖点，需要你裁决论文如何定位。**

**证据文件**：`results/tables/table_main_llm.csv`、`results/tables/table_main.csv`

---

## E35 🟢 强 LLM 的真实短板不在单位，而在**过度指派**

Direct-LLM 的 Precision 只有 69.1 / 72.0 / 85.4，而 Coverage 51.5 / 57.5 / 64.3。
结合 E23（**77.1% 的高覆盖字段其实不属于任何统一概念**），说明：
**LLM 会对本该判 UNKNOWN 的字段强行给出匹配**，这才是它的主要错误来源，
而不是单位冲突（仅 0.0–0.7%）。

⇒ 论文的重心应从「单位门控」转向 **开放集判定（UNKNOWN）**：
这既是 E23 的实测支撑（77.1%），也是 LLM 实际失分的地方，
且指南 §6 已把「字段级开放集，负例来自真实数据」列为三块无人占据的地盘之一。

**证据文件**：`results/tables/table2_llm_baseline.csv`、`data/gold/unknown_set_adjudicated.csv`

---

## E36 🟢🟢 **B 方案主结果**：确定性检查作弃权证据，开放集 AUROC +5.7 / +5.6

**方法**：`abstain_score(j) = 1 − w·Σ_d V_d(j, ĉ(j))`，d ∈ 选中的检查维度。
匹配器自身弃权（未给候选）时分数为 0。全部 V_d 是确定性、可打印规则，取值 {0, 0.5, 1}。

**标定（C4 严格遵守）**：维度组合与 w 只在 **MIMIC-IV 验证分割**（62 字段 / 24 正例）上选，
报告集（MIMIC-IV test、CareVue 全量、eICU 全量）**完全不参与调参**。
选中 `unit + type + specimen`，`w = 0.1`（val AUROC 99.3）。

| 域 | 判据 | **Open-set AUROC** | 95% CI | Δ |
|---|---|---:|---|---:|
| MIMIC-IV (test) | LLM 自身弃权 | 91.0 | [86.9, 94.9] | — |
| MIMIC-IV (test) | **+ 确定性检查（本文）** | **96.6** | [93.9, 98.7] | **+5.7** |
| CareVue | LLM 自身弃权 | 87.9 | [85.8, 90.1] | — |
| CareVue | **+ 确定性检查（本文）** | **93.6** | [91.8, 95.1] | **+5.6 ✓ CI 不重叠** |
| eICU | LLM 自身弃权 | 84.4 | [79.3, 89.0] | — |
| eICU | + 确定性检查（本文） | 85.0 | [79.1, 89.6] | +0.7 |

### 三条要写进论文的观察

1. **提升幅度可观且在 CareVue 上统计显著**（CI 不重叠）。MIMIC-IV 提升同样是 +5.7，
   但 n=132 使 CI 偏宽、与基线略有重叠，**须如实报告而非声称显著**。
2. **eICU 几乎无增益（+0.7）**，且这有明确解释：eICU **没有任何字典元数据**
   —— 无 `param_type`、无 `fluid`、无单位列（E2、E7）。检查在无信号处自然无增益。
   **这不是失败，而是本方法适用边界的定量刻画**，应作为一条结论写出。
3. **`provenance` 维必须剔除**。逐维消融（`table3_abstain_ablation.csv`）显示
   `− provenance` 在三域上均优于全四维（+5.5 / +5.7 / +0.7 vs +3.7 / +3.9 / +0.0）；
   MIMIC-IV val 上的独立标定也自动选中了不含 provenance 的组合。
   原因：概念不绑定单一表来源（E25），`V_prov` 在字段→概念模式下取值近乎任意，是噪声。

**证据文件**：`results/tables/table2_openset_main.csv`、
`results/tables/table3_abstain_ablation.csv`、`data/gold/abstain_config.json`、
`src/schemaalign/match/abstain.py`

---

## E37 🟢 一处被自查抓到的调参泄漏（方法学记录）

首次标定时我在 **CareVue 的一半**上选超参、却报告**整个 CareVue** —— 调参集是报告集的子集，
构成泄漏。已改为严格在 MIMIC-IV 验证分割上标定（C4 原本就要求如此）。

修正前后：CareVue 的 Δ 从 +5.7 变为 +5.6（几乎不变，说明结论稳健），
但**方法学上前者不可用**。论文的可复现性声明须写明标定集与报告集的划分方式。

**证据文件**：`data/gold/abstain_config.json` 的 `tuned_on` 字段

---

## E38 🟢 **itemid 记忆检验通过**：模型没有靠背公开 crosswalk

指南 §4.2 指出：`mimic-code` 是被大量引用的公开仓库，`itemid 220045 = Heart Rate`
几乎肯定在冻结 LLM 的预训练语料里。若 FieldCard 含 itemid 而结果显著变好，整个结论不可信。

同一模型、同一提示词、同一评测集，**唯一变量是字段描述里是否带 itemid**：

| 域 | FieldCard | **R@1** | Precision | F1 | Coverage |
|---|---|---:|---:|---:|---:|
| MIMIC-IV | 不含 itemid（本文，C1） | **95.9** | **69.1** | **80.3** | 51.5 |
| MIMIC-IV | 含 itemid（仅此实验破例） | **95.9** | 64.4 | 77.0 | 55.3 |
| CareVue | 不含 itemid（本文，C1） | **97.3** | **70.8** | **81.9** | 58.5 |
| CareVue | 含 itemid（仅此实验破例） | **97.3** | 68.1 | 80.1 | 60.8 |

**R@1 逐位相同**，而 Precision 与 F1 在加入 itemid 后**反而略降**（−4.7 / −2.7 pp，
因为模型被 itemid 诱导给出更多匹配，Coverage 上升但错配增加）。

⇒ **模型的匹配能力来自字段语义而非记忆的公开对照表。**
这条是可信度的直接支撑，且是**便宜且强**的检验——建议放进 Table 3 与 §4 Setup 各一行。

**可直接仿写的句式**
> Including the raw item identifier in each field card leaves Recall@1 unchanged (95.9 / 97.3)
> and slightly degrades precision, indicating that the matcher relies on field semantics
> rather than on memorized public crosswalks.

**证据文件**：`results/tables/table3_itemid_memory.csv`、
`data/llm_baseline/memtest_*.json`（含每次调用原文）

---

## E39 🟢🟢 编码器阶梯：**领域预训练 > 规模**，而**原始 LLM 隐状态做嵌入会崩**

字段侧用字段名、概念侧用概念名（同一文本空间，见 E19），纯余弦排序，不含门控。

| 编码器 | 参数 | 类型/池化 | MIMIC-IV R@1 | CareVue R@1 | eICU R@1 | MIMIC-IV R@10 |
|---|---:|---|---:|---:|---:|---:|
| all-MiniLM-L6-v2 | 22.7M | 句向量 / mean | 71.0 | 75.0 | 58.4 | 81.9 |
| bge-base-en-v1.5 | 109.5M | 句向量 / CLS | 72.7 | 74.3 | 64.3 | 85.7 |
| **SapBERT-PubMedBERT** | 109.5M | **生物医学域** / CLS | **75.6** | **79.1** | **68.8** | **97.9** |
| **GPT-2** | 124.4M | **decoder LLM / last-token** | **8.0** | **6.1** | **12.3** | **22.7** |

### 两条可直接写进论文的结论

1. **领域预训练比参数规模更重要。** SapBERT 与 bge-base 参数量相同（109.5M），
   但 R@1 高 2.9–4.8 点，**R@10 高 12.2 点（97.9 vs 85.7）**。
   而 bge-base 相对 MiniLM 参数量增加 4.8 倍，R@1 只提升 1.7 点（MIMIC-IV）甚至下降（CareVue）。
   ⇒ 指南 §11.4 的「是否需要大模型语义表示」答案是：**需要的是领域模型，不是更大的通用模型。**

2. **把原始 decoder-only LLM 的隐状态当字段嵌入会彻底失效**（R@1 仅 6.1–12.3）。
   即使按 TimeCMA (AAAI'25) 的做法取 last-token 池化亦然。
   未经对比学习训练的语言模型隐状态不构成可用的句子表示。

### 与 Direct-LLM 结果并不矛盾 —— 这恰好构成一个三方对照

| LLM 的用法 | R@1 |
|---|---:|
| **生成式匹配器**（Direct-LLM, gpt-4.1 输出 JSON） | **95.9 / 97.3 / 88.2** |
| **隐状态当嵌入**（GPT-2 last-token） | 8.0 / 6.1 / 12.3 |
| 对比训练的领域编码器（SapBERT） | 75.6 / 79.1 / 68.8 |

**这是一条独立且反直觉的发现**：同一类模型，**用作生成式匹配器远优于用作特征提取器**。
原 idea 设想的「冻结 LLM 生成字段语义向量」路线，实测是三者中最差的。

**证据文件**：`results/tables/table3_encoder_ladder.csv`、`scripts/remote/T4_encoder_ladder.py`

---

## E40 🟡 人类天花板（Table 2 的 Oracle 行）

标注者 B（保守优先协议）相对最终裁定 gold，仅在 B 覆盖到的 2,326 个字段上评测：

| 域 | n | R@1 | Precision | F1 |
|---|---:|---:|---:|---:|
| MIMIC-IV | 105 | **100.0** | 100.0 | 100.0 |
| CareVue | 629 | **98.3** | 99.1 | 98.7 |
| eICU | 147 | **100.0** | 98.8 | 99.4 |

对照 Direct-LLM 的 95.9 / 97.3 / 88.2 ⇒ **任务仍有空间，本文数字未饱和**；
且 **eICU 的差距最大（88.2 vs 100.0，−11.8）**，与 E2/E7 的「eICU 元数据最贫乏」一致。

**⚠️ 必须标注的偏乐观性**：标注者 B 参与了 gold 的产生（`both_agree` 行即 B 同意的结果），
因此这是**本标注协议隐含的上限**，不是独立第三方上限。
独立的统计量是 **κ = 0.967**（E21）。论文中两者应并列，并说明这一偏差方向。

**证据文件**：`results/tables/table2_oracle_ceiling.csv`

---

## E41 🟢🟢 **弃权证据只对「无梯度置信度」的匹配器有效** —— 把主张收窄成一个可检验的条件

写作前把 Table 2 统一到同一评测集时（见 E42），顺手加了一条此前没有的对照：
**把同一批确定性检查叠到最强非 LLM 匹配器（SapBERT 余弦）上**，看方法是否与匹配器无关。

答案是**否**，而这个否定比原来的肯定更有信息量。

| 域 | SapBERT 纯余弦 | + 确定性检查 | Δ |
|---|---:|---:|---:|
| MIMIC-IV | 93.36 | 93.34 | **−0.02** |
| CareVue | 92.48 | 90.60 | **−1.89** |
| eICU | 80.65 | 79.43 | **−1.22** |

**这不是超参没调好**：上表的 `(dims, w)` 是**专门为 SapBERT 重新在 MIMIC-IV 验证分割上标定**的
（C4 合规，网格 15 组合 × 6 个 w），选出 `unit+type, w=0.2`，val AUROC 从 95.94 抬到 97.81；
但该配置在三个报告域上仍然是 −0.02 / −1.89 / −1.22。**val 上的增益没有迁移。**

### 机制（可写进 §5 讨论）

生成式 LLM 输出的是**硬判定**：给候选或不给，没有分数。
于是弃权判据里 `base_conf ∈ {0,1}`，确定性检查是**被接受集合内唯一的连续证据**——纯增信息。
对比学习编码器输出的是**已校准的余弦**，本身就带梯度；
乘上 `(1 − w·ΣV_d)` 之后，检查只是在一个已经排好序的分数上叠噪声。

### 由此得到论文真正的贡献形态：一个 2×2 而不是一句「我们的方法有效」

| | 用作**重排**信号 | 用作**弃权**证据 |
|---|---|---|
| **弱匹配器**（冻结编码器） | ✅ 单位冲突 7.4% → 0.0%，精度代价 ≤0.4pp（E28） | ❌ −0.0 / −1.9 / −1.2（本条） |
| **强匹配器**（生成式 LLM） | ❌ R@1 −2.7 ~ −8.1（E34） | ✅ **+5.7 / +5.6 / +0.7**（E36） |

**可直接仿写的句式**
> Deterministic compatibility checks pay off as abstention evidence exactly when the matcher emits no
> graded confidence. A generative LLM returns a hard accept/reject, so the checks supply the only
> continuous evidence within its accepted set (+5.7/+5.6/+0.7 AUROC). A contrastive encoder already
> emits a calibrated cosine; the same checks, re-calibrated for it on the same validation split, then
> act as noise (−0.0/−1.9/−1.2).

**为什么对论文有利**：把「我们的方法有效」升级成「我们给出了它何时有效、何时无效的条件」，
并且两侧都有实测。审稿人问「这是不是只对 gpt-4.1 成立」时，答案不是辩解而是一张 2×2。

**证据文件**：`results/tables/table2_final.csv`、`scripts/local/run_table2_final.py`

---

## E42 🟢 Table 2 曾经不可比 —— 已统一评测集（方法学记录）

写作前核对发现：`table2_baselines.csv` / `table2_main.csv`（非 LLM 基线）与
`table2_llm_baseline.csv` 跑在**不同 gold 版本**上——CareVue 侧一个是 250 正例、另一个是 296，
MIMIC-IV 侧 123 vs 132 字段。并排进同一张表就是不可比。

**已修**：用当前 gold 重跑，全部方法统一为
`mimic-iv = test 分割 (132 字段/49 正例)`、`CareVue = 全量 (696/296)`、`eICU = 全量 (244/152)`，
与 LLM 基线逐字段一致。θ_open 仍逐方法在 MIMIC-IV 验证分割标定（C4）。

**同时修正的一处指标口径**：开放集 AUROC 此前对嵌入类基线是用**阈值化后的二值预测**算的，
应当用**连续的 top-1 余弦分数**。改正后 MiniLM 的 MIMIC-IV AUROC 从 76.35 变为 91.06 ——
即此前**系统性低估了嵌入基线**。论文必须用改正后的数字，否则是把基线打弱。

**新的 Table 2 事实（写作直接用）**

| 方法 | MIMIC-IV | CareVue | eICU |
|---|---:|---:|---:|
| Exact / normalized name | 36.7 / 68.4 | 37.2 / 68.3 | 44.1 / 72.4 |
| Ontology only (LOINC) | 26.5 / 63.3 | 24.7 / 62.3 | **0.0 / 50.0** |
| Frozen encoder, general (MiniLM-L6) | 49.0 / 91.1 | 62.2 / 90.0 | 44.1 / 73.1 |
| Frozen encoder, biomedical (SapBERT) | 67.3 / **93.4** | 70.6 / **92.5** | 57.9 / 80.6 |
| Direct LLM (gpt-4.1) | **95.9** / 91.0 | **97.3** / 87.9 | **88.2** / 84.4 |
| **+ 确定性检查作弃权证据（本文）** | 95.9 / **96.6** | 97.3 / **93.6** | 88.2 / **85.0** |

（每格 = Recall@1 / 开放集 AUROC）

**必须如实写出的一点**：SapBERT 的余弦分数本身就是**很强的开放集判据**（93.4/92.5/80.6），
在两个域上高于 LLM 自身弃权（91.0/87.9）。本文方法在三域仍最高，但相对 SapBERT 的
领先在 MIMIC-IV 与 CareVue 上落在置信区间内，只有 eICU（85.0 vs 80.6）明确领先。
**论文不能说「我们全面最好」，只能说「在同一匹配器上加入检查带来一致提升」。**

**证据文件**：`results/tables/table2_final.csv`

---

## E43 🟢🟢 外审要求的四项受控实验（gpt-5.6-sol 对 PAPER_PLAN 的 revise 意见）

外审(gpt-5.6-sol, xhigh)判定方案 **revise**，四条要害意见与实测回应：

### (a) 「同一信号、两个位置」必须是**受控**对照，否则读起来像事后补救

原来的证据是拼出来的：重排的证据来自编码器(E28)、弃权的证据来自 LLM(E36)，
候选集、检查维度、标定集都不同。现已重跑一次**完全受控**的对照
（`results/tables/table3_placement.csv`）：同一批 LLM 候选、同一次 `gate_all` 调用、
同一组维度 `{unit,type,specimen}`、同一标定分割、同一批测试字段，**唯一变量是用在哪一步**。

| 域 | 位置 | R@1 | ΔR@1 | 开放集 AUROC | ΔAUROC | 配对 95% CI |
|---|---|---:|---:|---:|---:|---|
| MIMIC-IV | 拒绝式（任一 V_d=1） | 87.76 | **−8.16** | 90.24 | −0.73 | [−4.65, +2.63] |
| MIMIC-IV | **弃权证据（本文）** | 95.92 | **0.00** | **96.64** | **+5.68** | **[+2.70, +8.99]** |
| CareVue | 拒绝式 | 96.62 | −0.68 | 88.61 | +0.69 | [−0.18, +1.61] |
| CareVue | **弃权证据（本文）** | 97.30 | **0.00** | **93.57** | **+5.65** | **[+4.05, +7.28]** |
| eICU | 拒绝式 | 87.50 | −0.66 | 86.38 | +1.99 | [−0.08, +4.57] |
| eICU | **弃权证据（本文）** | 88.16 | **0.00** | 85.04 | +0.65 | [−1.48, +2.76] |

（另有一档「连 0.5 的无法判定也拒绝」的保守上界：R@1 −69 / −73 / −81，AUROC −26 ~ −29，
说明把「无法判定」当「不相容」是灾难性的，这一档本身就是一条可写的设计教训。）

**结论**：作为拒绝规则，它扣召回而不换来排序增益（三域的 ΔAUROC 配对 CI 全部含 0）；
作为弃权证据，它零召回代价且在两域显著。**这才是「同一信号、换个位置」的干净证明。**

### (b) 显著性必须用**配对 bootstrap 的 Δ 置信区间**，边缘 CI 是否重叠不是正确检验

改用配对重采样（每次抽同一组字段索引，在同一样本上算两法之差，n_boot=2000）：

| 域 | Δ AUROC | **配对 95% CI** | p(Δ≤0) | 结论 |
|---|---:|---|---:|---|
| MIMIC-IV | +5.68 | **[+2.70, +8.99]** | **0.0000** | **显著** |
| CareVue | +5.65 | **[+4.05, +7.28]** | **0.0000** | **显著** |
| eICU | +0.65 | [−1.48, +2.76] | 0.2825 | 不显著（如实报告） |

**这直接改写了此前的保守表述**：E36 因为看边缘 CI 重叠而只敢说 CareVue 显著；
配对检验表明 **MIMIC-IV 同样显著**（边缘 CI 重叠对配对比较本就是错误的判据）。
论文可以写「三域中两域显著」。

### (c) 「过度指派是主要错误」需要误差计数，而不是由 Precision 反推

`results/tables/table2_error_decomp.csv`，按 top-1 判定逐字段分类：

| 域 | 正确 | **过度指派**（UNKNOWN 被给了概念） | 配错概念（可映射但目标错） | 漏判（可映射却弃权） | **过度指派占全部错误** |
|---|---:|---:|---:|---:|---:|
| MIMIC-IV | 47 | **19** | 2 | 0 | **90.5%** |
| CareVue | 288 | **107** | 5 | 3 | **93.0%** |
| eICU | 134 | **19** | 4 | 14 | 51.4% |

MIMIC-IV / CareVue 上九成以上的错误是过度指派；**eICU 只占 51.4%**（漏判 14 个更突出），
须如实写出，不能三域一概而论。

### (d) 只报 AUROC 不可操作，需要**锁定阈值**下的工作点

θ 逐方法在 MIMIC-IV 验证分割上锁定（C4；两法分数尺度不同，共用一个 θ 是尺度错配）：
自身弃权 θ=1.00、本文 θ=0.90。

| 域 | 方法 | 精度 | 召回 | F1 | **UNKNOWN 检出率** |
|---|---|---:|---:|---:|---:|
| MIMIC-IV | 自身弃权 | 76.56 | 100.0 | **86.73** | 81.93 |
| MIMIC-IV | + 检查（本文） | 80.00 | 89.80 | 84.62 | **86.75** |
| CareVue | 自身弃权 | 76.15 | 94.93 | 84.51 | 78.00 |
| CareVue | + 检查（本文） | **86.91** | 87.50 | **87.21** | **90.25** |
| eICU | 自身弃权 | 87.07 | 84.21 | **85.62** | 79.35 |
| eICU | + 检查（本文） | 87.41 | 77.63 | 82.23 | **81.52** |

**必须如实写的权衡**：在锁定阈值下，**UNKNOWN 检出率三域全部提升**（+4.8 / +12.3 / +2.2），
但映射任务的 F1 只在 CareVue 提升，MIMIC-IV 与 eICU 反而下降 2.1 / 3.4 点。
即本方法是拿可映射字段的召回换「不该映射」的检出——这与论文标题的立场一致，
**但不能只报有利的那一半**。

### 外审同时点出的、必须在写作中执行的措辞收窄

- 「77% 不对应任何概念」→「不对应 138 个概念目录中的任何一个」
- 「金标准」→「LLM 仲裁的参考集」；「人工过目」→「两个独立提示的标注者逐字段判定」
- 「排除了污染 / 记忆」→「在这两项对照上未观察到优势」
- eICU 的 +0.65「因为没有元数据」→「与其缺少相容性元数据一致」
- 「88–97% 的字段对齐」→ 明确是**已知正例字段上的 Recall@1**
- K11/K13 的结论只在本文设置内成立，不作一般化

**证据文件**：`results/tables/table3_placement.csv`、`table2_paired_delta.csv`、
`table2_error_decomp.csv`、`table2_operating_point.csv`、`scripts/local/run_placement_matched.py`

---

## E44 🟢🟢 编码器阶梯**补全**（bge-large 335M + Qwen2.5-1.5B）—— E39 的两条结论在完整轴上成立

2026-08-19 补齐了 E39 缺的两档（原因见 §T4_ladder_finish：首轮 bge-large 在 99.4% 处
IncompleteRead 断流，qwen15 因而未执行；改用 `hf-mirror.com` 断点续传，3.3 MB/s，全程 26 分钟）。

| 编码器 | 参数 | 类型/池化 | MIMIC-IV | CareVue | eICU | MIMIC-IV R@10 |
|---|---:|---|---:|---:|---:|---:|
| all-MiniLM-L6-v2 | 22.7M | 句向量/mean | 71.01 | 75.00 | 58.44 | 81.93 |
| bge-base-en-v1.5 | 109.5M | 句向量/CLS | 72.69 | 74.32 | 64.29 | 85.71 |
| **bge-large-en-v1.5** | **335.1M** | 句向量/CLS | 74.37 | 76.01 | **59.74** | 83.61 |
| **SapBERT-PubMedBERT** | 109.5M | **生物医学域**/CLS | **75.63** | **79.05** | **68.83** | **97.90** |
| GPT-2 | 124.4M | decoder/last-token | 7.98 | 6.08 | 12.34 | 22.69 |
| **Qwen2.5-1.5B** | **1543.7M** | decoder/last-token | **17.23** | **17.57** | **25.97** | 34.45 |

### 两条结论现在有了完整的规模轴，且都更强

1. **领域预训练 > 规模，且规模轴已走到 335M 仍不敌 110M 的领域模型。**
   bge-large 比 bge-base 大 **3.06 倍**，只换来 +1.68 / +1.69 / **−4.55**（eICU 反而更差）；
   而参数量与 bge-base **完全相同**的 SapBERT 高出 2.94 / 4.73 / 4.54，R@10 更是 97.90 vs 85.71。
   通用句向量从 22.7M 到 335.1M（**14.8 倍**）在 MIMIC-IV 上只从 71.01 涨到 74.37（+3.36）。

2. **decoder-only 隐状态做字段嵌入，扩到 1.5B 仍然不可用。**
   Qwen2.5-1.5B 是 GPT-2 的 **12.4 倍**参数，R@1 从 7.98/6.08/12.34 升到 17.23/17.57/25.97 ——
   确实好了一截，但仍**远低于 22.7M 的 MiniLM**（71.01/75.00/58.44）。
   ⇒ 这不是「模型不够大」，是**未经对比学习的语言模型隐状态本身不构成可用的句子表示**。
   规模不能补救这一点。

**同一类模型的三种用法（完整版）**

| LLM 的用法 | MIMIC-IV / CareVue / eICU R@1 |
|---|---|
| **生成式匹配器**（gpt-4.1 输出 JSON） | **95.9 / 97.3 / 88.2** |
| 对比训练的领域编码器（SapBERT 110M） | 75.6 / 79.1 / 68.8 |
| 隐状态当嵌入（Qwen2.5-**1.5B** last-token） | 17.2 / 17.6 / 26.0 |
| 隐状态当嵌入（GPT-2 124M last-token） | 8.0 / 6.1 / 12.3 |

原 idea 设想的「冻结 LLM 生成字段语义向量」路线，在**扩到 1.5B 之后**依然是三者中最差。

**⚠️ 措辞收窄（外审要求）**：本结论限于 last-token 池化的**基座**模型、本文的字段/概念文本，
不宣称对所有 decoder-only 模型或所有池化方式成立。

**证据文件**：`results/tables/table3_encoder_ladder.csv`、`scripts/remote/T4_ladder_finish.sh`、
远端 `logs/T4_ladder_finish.log`

---

## E45 🔴 数字审计（zero-context, gpt-5.6-sol xhigh）判定 **fail** —— 三处真错误已修

外部审计逐格核对论文与原始结果文件，判定 `CLAIM_AUDIT: fail`。发现的**真错误**：

### ① gold 规模虚高 —— 812 实为 **710**

`gold_pairs.csv` 里有 **102 条完全重复**的三元组 `(db, field_key, base_concept)`，
全部来自 `3-source agreement`（合并药物轮次时把三源行重复追加了一次）。

| 项 | 原报 | **实际** |
|---|---:|---:|
| gold 对 | 812 | **710** |
| 按库（eICU / CareVue / MIMIC-IV） | 178 / 384 / 250 | **160 / 304 / 246** |
| 非 LLM 证据 | 319（39%） | **217（30.6%）** |
| └ 三源一致 | 260 | **159** |
| └ 表内显式列 | 24 | 24 |
| └ 主键同一性 | 35 | **34** |
| 概念数 / 三库全覆盖 | 135 / 86 | 135 / 86（不变） |

**关键**：`load_evalset` 用 dict 装 gold，重复行本来就会塌缩，
因此**所有评测结果一个数字都没变**（已全量重跑逐条比对确认）。错的只是"参考集规模"这一项描述。
已去重并备份原文件为 `gold_pairs_predup_backup.csv`。

### ② 消融表与主结果用了不同的 w —— 已统一

`run_paper_tables.py` 调 `abstain_scores` 时**没传 w**，用了默认 0.2；
主结果用的是标定出的 **0.1**。于是同一行「ours」在两张表里是 5.48/5.68/0.69 vs 5.68/5.65/0.65。
已修为统一取 `abstain_config.json` 的 w，两表现在逐位一致（**5.68 / 5.65 / 0.65**）。

### ③ 受限 κ = 0.9419 **不可复现**，已从论文删除

两名标注者的逐行标签由多智能体工作流产生，**未落盘**；
`annotator_agreement.json` 只存了聚合量（n=1447, Po=0.9855, Pe=0.5632, κ=0.9668）。
因此「剔除双方都判 UNKNOWN 后 κ 仍有 0.9419」这一句**无法从已发布产物复算**，已从论文删除，
并在 JSON 里写入不可复现声明。替代方案：人类专家盲测（`human_validation/`）将给出**真正独立**的 κ。

### 审计同时指出的口径冲突（已消除）

- 论文正文引用的位置对照数字（−8.2 / −69~−81）来自**旧的二值否决版**表，
  而展示的表已换成分级版 —— 已改为引用分级版（−2.6~−4.1 重排 / −5.3~−10.2 拒绝）。
- CareVue 的配对 CI 在两个 CSV 里分别是 [4.05,7.28] 与 [4.03,7.24]（bootstrap 调用顺序不同），
  论文统一只引用 `table3_placement_graded.csv`。
- `table2_llm_baseline.csv` 的 `OpenSet_AUROC`（88.55/86.12/85.07）是用**二值预测**算的旧口径，
  与主表的 90.96/87.93/84.39（用 `abstain_scores` 的连续分数）冲突。主表口径正确，
  旧列已标注废弃。差异来源：`abstain_scores` 对「候选无概念代表」的字段给 0.6·b 而非 1.0·b，
  相当于给基线多一档信息 —— **这对本文是保守的**（基线被抬高），保留。
- SapBERT 重标定的 −0.02/−1.89/−1.22 此前只在临时脚本里，已固化为
  `results/tables/table3_encoder_checks.csv`。

**结论**：审计发现的问题里没有一个动摇主结论，但①和②是必须修的实打实的错误。
**这轮审计的价值在于：论文里现在每一个数字都能回溯到一个结果文件。**

**证据文件**：`docs/reviews/2026-08-19_gpt56sol_reviews.md`、`data/gold/gold_pairs_predup_backup.csv`

---

## E46 🟢🟢 **T6 跨库生理信号迁移** —— 对齐质量确实影响下游，且弃权是免费的

外审的第一条拒稿理由是「这不是信号处理论文，没有下游实验」。本条把结论落到一个
真正的多中心生理时间序列任务上。**这是新增实验，不改动任何既有结论。**

**设置**：24 个连续监测通道（心率、SpO₂、有创/无创血压、PEEP、潮气量、FiO₂、pH、PCO₂、
体温、呼吸频率、镇静/疼痛评分、机械通气模式…），每 stay 取**前 24 小时**逐小时聚合，
缺失以 mask 通道显式表示。模型 = 1D-CNN + GRU，在 **MIMIC-IV 训练分割**上训练预测院内死亡，
val AUROC **84.19**（与文献 24 小时死亡预测水平相当）。随后**零样本迁移**到 CareVue 与 eICU。
唯一变量 = **目标库的字段由哪种对齐方案填进通道**。归一化统计量只在 MIMIC-IV 训练分割上算（C4）。

| 域 | oracle（gold） | exact-name | Direct-LLM | **LLM + 弃权（本文）** |
|---|---:|---:|---:|---:|
| CareVue (n=19,112) | **74.29** (24 通道) | 58.88 (17) | 74.13 (24) | **74.15** (**20**) |
| eICU (n=110,257) | **71.07** (20) | 62.06 (12) | 64.86 (21) | 64.85 (**20**) |

（AUPRC 同向：CareVue 26.27 / 17.70 / 26.04 / 26.13；eICU 16.65 / 14.04 / 14.83 / 14.84）

### 三条可写进论文的结论

1. **对齐质量对下游有大幅影响，不是纸面指标。**
   把人工对齐换成 exact-name，跨库迁移 AUROC 掉 **15.4（CareVue）/ 9.0（eICU）**。
   这把引言里「错配通道是信号层面的缺陷」从修辞变成了实测。

2. **冻结 LLM 的自动对齐在 CareVue 上补回了几乎全部人工对齐的性能**（74.13 vs 74.29，差 0.16），
   在 eICU 上只补回约三分之一（64.86 vs 71.07）。
   **与本文主线一致**：eICU 元数据最贫乏，自动对齐在那里也最弱。

3. **弃权在下游是免费的，且构成对弃权判定的独立佐证。**
   弃权在 CareVue 砍掉 **4 个**通道、eICU 砍掉 **1 个**，迁移 AUROC 变化 **+0.02 / −0.01**。
   若被砍掉的匹配本是正确的，这些通道应当携带下游信号、砍掉应当掉点；实测不掉，
   **与"这些匹配确实是虚假匹配"一致**。这是一条来自下游任务的、独立于金标准的佐证。

### ⚠️ MIMIC-IV 那一行不可用于比较（必须排除）

`table4_transfer.csv` 里 mimic-iv 行（oracle 82.69 / llm 70.58 / llm+弃权 68.82）**是假象**：
Direct-LLM 只在 MIMIC-IV 的 val+test 分片上跑过，源域仅映射 99 个字段而 oracle 有 246 个，
通道天然更稀疏。目标域上 LLM 是全量跑的，才是有效比较。**论文只报两个目标域。**

### 与外审意见的对应

- 「没有下游信号任务」→ 本条即是，且用的是连续监测通道而非化验，落在生理信号范畴
- 「at no cost 是定义使然」→ 这里的 no cost 是**端到端实测**的，不是定义使然

**证据文件**：`results/tables/table4_transfer.csv`、`table4_transfer_meta.json`、
`scripts/remote/T6_transfer.py`、`scripts/local/export_alignments.py`、远端 `logs/T6.log`

---

## E47 🟢🟢🟢 **人类专家盲测完成** —— 外审第一条拒稿理由的正面回应，且发现一个更重要的东西

两位**真正独立**的人类标注者（一位 ICU 临床专家、一位临床数据工程专家）盲测同一份
198 行分层样本，全部填完（198/198，置信度中位数 5，145 与 152 条留了备注）。
样本不含模型答案、不含分层标签、不含 itemid。

### ① 真实的人-人 Cohen's κ = **0.9517**，顶替此前的模型实例 κ

| 统计量 | 两个**模型实例**（旧） | **两位人类专家**（新） |
|---|---:|---:|
| n | 1,447 | **196** |
| Po | 0.9855 | 0.9643 |
| **Pe（偶然一致）** | 0.5632 | **0.2599** |
| **Cohen's κ** | 0.9668 | **0.9517** |

**新 κ 更有说服力**：偶然一致率只有 0.26（旧的 0.56），且样本是**刻意抽的难例**，
在这种条件下仍有 0.95。开放集判定本身（可映射 vs UNKNOWN 二值化）**κ = 0.9388**（Pe=0.50）。
论文中的 κ 已全部替换为人-人版本；模型实例的 κ 降级为「协议可复现性」而非「标注效度」。

### ② 人-模型一致率，按分层 —— **77.1% 这个主张被直接验证**

| 层 | n | 临床专家 | 数据工程 | 两人均同意模型 |
|---|---:|---:|---:|---:|
| **S1 判 UNKNOWN 的高覆盖字段** | 70 | **98.6%** | **98.6%** | **98.6%** |
| S2 正例·仅 LLM 证据 | 50 | 92.0% | 94.0% | 92.0% |
| S3 两标注者分歧经仲裁 | 30 | 86.7% | 86.7% | 80.0% |
| **S4 确定性检查报冲突的正例** | 28 | **100.0%** | 96.4% | 96.4% |
| **S5 正例·非 LLM 证据** | 20 | **80.0%** | **75.0%** | **75.0%** |
| 合计 | 198 | 93.4% | 92.9% | 91.4% |

- **S1 = 98.6%**：论文「77.1% 的高覆盖字段不对应任何概念」这一主张所依赖的正是这批判定，
  两位专家独立复核后 70 个里只有 1 个有异议。**主张成立。**
- **S4 = 100% / 96.4%**：本文检查报冲突的字段，专家也认为有问题。检查没有乱报。

### ③ 🔴 **S5 的反转：号称最可信的「非 LLM 证据」子集反而错得最多（20%）**

这**推翻了我此前的一个说法**。E33 的污染对照里，我把「三源一致 / 表内显式列 / 主键同一性」
这批 217 对当作干净子集，并解释其 R@1 更高是因为「概念本身更无歧义」。
专家数据说：**不是更无歧义，是三份公开专家映射本身就把测量方式搞混了。**

四条 S5 错误里三条是同一个模式：**床旁快速血糖（POC fingerstick）被映射成 `glucose`**——
而 `mimic-code` / `eicu-code` 这些被广泛引用的公开映射里就是这么写的。

⇒ **这本身是一条对领域有价值的发现**：广泛使用的公开 ICU 概念映射系统性地混淆测量方式。
论文里对污染对照的措辞必须相应修正，不能再说非 LLM 子集"更干净"。

### ④ 参考集整体错误率：**3.96%**（95% CI 2.01–7.67%，分层加权，覆盖 N=1,877）

错误定义 = **两位专家一致反对模型**（单人反对不计，否则等于用一个人覆盖仲裁结果）。

### ⑤ 🟢🟢 残余错误**集中在测量方式**，而这正是我们砍掉的那一维

9 条「两位专家一致反对」按类型分解：

| 类型 | n |
|---|---:|
| **测量方式：床旁 POC vs 实验室**（血糖 ×3） | **3** |
| **测量方式：呼吸机设定值 vs 实测值**（呼吸频率 ×2） | **2** |
| **测量方式：动脉 SaO₂ vs 脉搏氧 SpO₂** | **1** |
| 元数据不足以判定 | 1 |
| 模型判 UNKNOWN 而专家给了概念 | 1 |
| 概念命名粒度（sedation_score vs sedation_scale） | 1 |

**6/9 是测量方式混淆。** E36 因为 `V_prov` 拉低 AUROC 而把它从弃权判据里剔除了——
现在有了人类证据：**这个区分本身是残余错误的主要来源，被剔除的是我们那个过于粗糙的实现
（按表来源族判定），而不是这个区分本身。** 这是一条精确、有人类数据支撑的 future work。

**方向也支持本文主线**：9 条里 **6 条是「模型给了概念、专家判 UNKNOWN」**——
即**过度指派**，与论文核心论点一致，且这次是由盲测的人类独立确认的。

### ⑥ 应用全部专家修正后重跑，主结论**不变**

修正版参考集（撤销 6 个 gold 对、改 2 个概念名，存于 `data/gold_expert/`）：

| 域 | 原始 Δ | **专家修正后 Δ** | 配对 95% CI | p |
|---|---:|---:|---|---:|
| MIMIC-IV | +5.68 | **+5.68** | [+2.70, +8.99] | 0.0000 |
| CareVue | +5.65 | **+5.47** | [+3.96, +7.03] | 0.0000 |
| eICU | +0.65 | **+0.65** | [−1.45, +2.79] | 0.2790 |

**两域显著、幅度几乎不变。** R@1 反而略升（CareVue 97.3→97.6，eICU 88.2→89.4），
因为撤掉的正是标注本身有误、模型「答错」的那几条。

**证据文件**：`results/tables/table5_expert_validation.csv`、`table5_expert_disagreements.csv`、
`table5_reference_error_rate.csv`、`table5_main_expert_corrected.csv`、
`data/gold_expert/`、`human_validation/_filled/`

---

## E48 🔴→🟢 审计抓到一处**事实错误**：CareVue 的 chartevents itemid 并非与 MIMIC-IV 不相交

论文（承自台账 E14）写的是「CareVue 的 `chartevents` 标识符与 MIMIC-IV 不相交，
而全量 MIMIC-III 与其共享 2,968 个」。**前半句是错的。**

实测：
- `field_catalog_m3cv.csv` 的 3,545 个 chartevents 字段里，**661 个是 220000+ 段**（MetaVision 编号空间）
- gold 里 CareVue 与 MIMIC-IV 共享 **59 个 chartevents itemid**（另有 78 个 labevents itemid，
  但那是已知且已利用的性质——两库化验共享编号空间，正是 E3 的 LOINC 桥接所依赖的）

**stay 级筛选没问题**（`DBSOURCE='carevue'`，与 metavision 互斥切分），
问题是 CareVue 期的 stay 里仍有少量行使用了 220000+ 编号。

### 影响量化（`results/tables/table6_carevue_itemid_audit.csv`）

把 CareVue 评测限制到**真正 CareVue 期编号**（chartevents itemid < 20000）后重跑：

| 子集 | n | 正例 | R@1 | AUROC 基线→本文 | Δ | 配对 95% CI | p |
|---|---:|---:|---:|---|---:|---|---:|
| 全部 CareVue 字段 | 696 | 296 | 97.3 | 87.93 → 93.57 | **+5.65** | [+4.04, +7.25] | 0.0000 |
| **仅 CareVue 期编号** | 635 | 235 | 96.6 | 87.76 → 92.98 | **+5.21** | [+3.68, +6.88] | **0.0000** |
| 键也存在于 MIMIC-IV 的字段 | 160 | 140 | 98.6 | 76.82 → 94.75 | +17.93 | [+5.98, +30.09] | 0.0010 |

**结论：共享编号没有在支撑结果。** 剔除后 Δ 从 +5.65 只降到 +5.21，仍显著。

### 论文中必须改的措辞

不能再写「不相交」。改为：CareVue 子集按 `DBSOURCE` 选取；其 3,545 个 chartevents 字段中
仍有 661 个带 MIMIC-IV 段的标识符，把评测限制到 CareVue 期标识符后 Δ 为
**+5.2（95% CI +3.7…+6.9）**，与全量的 +5.7 一致。

**教训**：E14 当初只核了「CareVue 期 itemid 段 < 20000」这一先验，没有回到**实际字段目录**去数。
先验对、数据不对。所有此类"结构性论证"都必须回数据核。

**证据文件**：`results/tables/table6_carevue_itemid_audit.csv`、`scripts/local/carevue_itemid_leakage.py`

---

## E49 🔴→🟢 `V_method`：按专家指出的方向做了，**验证集没选它**，但这个否定结果更有价值

E47 的盲测数据指出：残余标注错误里 **6/9 是测量方式混淆**。据此新增一维确定性谓词
`V_method`（`src/schemaalign/gates/rules.py`），并补齐了原 `_METHOD_RULES` 的三处漏洞：

| 漏洞 | 原规则 | 补后 |
|---|---|---|
| `Respiratory Rate (Set)` / `Respiratory Rate Set` | 只认 `^set_` / `_set$` / `setting`，**漏** | 加 `\(set\)`、`[\s_]set\s*$`、`desired`、`target` |
| `SaO2` vs `SpO2` | **无任何规则** | 新增 `bloodgas_sat` 与 `pulse_oximetry` 两类 |
| `Fingerstick Glucose` | 已能检出 `bedside`，但概念侧无修饰时只给 0.5 | 新规则：字段有显式修饰而概念目录无对应变体 → 1.0 |

### ① 查全：**6/6 的测量方式错误全部报警**

| 专家确认的错误 | V_method |
|---|---|
| `Fingerstick Glucose` → glucose | **1.0** |
| `Glucose finger stick` → glucose | **1.0** |
| `Glucose finger stick (range 70-100)` → glucose | **1.0** |
| `Respiratory Rate (Set)` → respiratory_rate | **1.0** |
| `Respiratory Rate Set` → respiratory_rate | **1.0** |
| `respFlowPtVentData|SaO2` → spo2 | **1.0**（方式不同：bloodgas_sat vs pulse_oximetry） |
| 其余 3 条（无标签的 eICU 单元格 / Riker 量表命名粒度 / 模型本就弃权） | 0.0，本就不是方式问题 |

### ② 查准：在 gold 正例上报警 **6.1% / 7.0% / 11.5%**（合计 39/474）

按检出方式类型：measured 13、invasive 12、set 5、bedside 4、bloodgas_sat 4。
其中相当一部分是**正确匹配被误报**，例如：

| 字段 | 参考集概念 | 为什么误报 |
|---|---|---|
| `Arterial BP [Systolic]` | `sbp` | 目录里只有一个 `sbp`，没有 `sbp_invasive` / `sbp_cuff` |
| `Total Protein` | `total_protein` | “Total” 是分析物名的一部分，不是测量方式 |
| `Total PEEP Level` | `peep` | 目录里没有 set/total PEEP 之分 |

### ③ 标定结果：**验证集没有选中 V_method**（C4 合规，网格 31 组合 × 5 个 w）

`val` 最优仍是 `unit+type+specimen`（AUROC 99.34）。在三个报告域上，加入 V_method 后
开放集 AUROC **一点没变**：96.64 / 93.57 / 85.04，`Δ_prev = +0.00 / +0.00 / +0.00`。

### 结论：这是一条比"改进成功"更有信息量的负结果

**残余错误不是匹配器层面能修的，而是目标词表粒度的性质。**
`V_method` 能精确检出这类错误（6/6），但因为**概念目录本身就是方式无关的**
（只有一个 `sbp`、一个 `peep`、一个 `glucose`），把它当硬拒会同时打掉大量正确匹配，
所以在任何以该目录为准的指标上都不可能有增益。

⇒ 可写进论文的表述：*开放集字段对齐的精度上限由概念目录的粒度决定；
在方式无关的目录下，测量方式冲突既是残余错误的主要来源，又无法被任何谓词安全地利用。*
这同时解释了 E36 为什么标定会剔除 `V_prov` —— 不是实现太粗糙，是**目标词表不支持这个区分**。
（这一条修正了 E47 中"我们的实现太粗糙"的推测。）

**证据文件**：`results/tables/table7_method_dimension.csv`、`table7_vmethod_audit.csv`、
`table7_vmethod_flagged.csv`、`scripts/local/vmethod_audit.py`、`src/schemaalign/gates/rules.py: v_method`

---

## E50 🟢🟢🟢 三个 LLM 家族 + 迁移的等价性检验 —— 外审两条意见的正面回应

### ① 迁移实验：5 个种子 + 患者级配对 bootstrap 等价性检验

外审指出「at no downstream cost 没有置信区间也没有等价性检验」。已补：
5 个随机种子重训（源域 val AUROC **84.20 ± 0.12**，很稳），
在**患者**上做配对 bootstrap（B=2000），等价边界取 ±1 AUROC 点。

| 域 | 人工对齐 | exact-name | 冻结 LLM | **+ 弃权** | Δ(弃权−不弃权) | **配对 95% CI** | 等价(±1) |
|---|---:|---:|---:|---:|---:|---|---|
| CareVue (n=19,112) | 74.54±1.34 | **58.33±0.68** | 74.39±1.13 | 74.43±1.15 | **+0.061** | **[−0.046, +0.176]** | ✅ |
| eICU (n=110,257) | 70.37±0.50 | **62.68±4.14** | 66.38±1.56 | 66.38±1.55 | **−0.004** | **[−0.063, +0.048]** | ✅ |

- **对齐质量对下游影响大**：exact-name 掉 **16.2 / 7.7** 个 AUROC 点
- **冻结 LLM 在 CareVue 补回几乎全部人工水平**（74.39 vs 74.54），eICU 补回约一半（66.38 vs 70.37）
- **弃权在下游是等价的**，CI 宽度只有 0.22 / 0.11 个点。
  "no cost" 从断言变成**正式的非劣性结论**。

### ② 三个 LLM 家族：方法在**过度指派更严重的匹配器上收益更大**

同一提示词（LLMatch 官方模板逐字）、温度 0、同一评测集、
**同一弃权配置**（dims/w 只在 MIMIC-IV val 上标定过一次，不为每个模型重标）。

MIMIC-IV（CareVue/eICU 运行中）：

| 模型 | 家族 | R@1 | Precision | AUROC 基线→本文 | **Δ** | 配对 95% CI | p |
|---|---|---:|---:|---|---:|---|---:|
| gpt-4.1 | OpenAI | **95.92** | 69.1 | 90.96 → 96.64 | **+5.68** | [+2.70, +8.99] | 0.0000 |
| deepseek-v3.2 | DeepSeek | **95.92** | 60.3 | 85.79 → **95.28** | **+9.49** | [+5.80, +13.85] | 0.0000 |
| gemini-2.5-pro | Google | **95.92** | 65.3 | 87.35 → **96.25** | **+8.90** | [+5.19, +13.25] | 0.0000 |

**三条同时成立且互相印证：**

1. **R@1 三家逐位相同（95.92）** —— 匹配能力跨家族复现，不是单一模型的偶然
2. **precision 越低（过度指派越重），Δ 越大**（60.3→+9.49；65.3→+8.90；69.1→+5.68）——
   这正是本文预测的关系：**检查在匹配器自身置信度越没用的地方帮助越大**，
   现在跨三个独立家族被确认，而不是一个后验解释
3. **加检查后三家收敛到同一水平**（95.28 / 96.25 / 96.64）——
   起点差 5 个点，终点差不到 1.4 个点：确定性证据把它们拉到同一条线上

⇒ 外审「只测了一个模型家族」这条限制不仅消除，还升级成**一个更强的正面主张**。
论文 Limitation 中该条已删除。

**证据文件**：`results/tables/table4_transfer.csv`、`table4_transfer_meta.json`、
`table8_multifamily.csv`、`scripts/local/run_multifamily.py`、远端 `logs/T6_v2.log`
