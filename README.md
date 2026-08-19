# Knowing When Not to Match: Open-Set Field Alignment across ICU Databases

Code and derived artefacts for the ICASSP 2027 submission. Anonymous review copy.

---

## ⚠️ What is NOT in this repository, and why

This work uses **MIMIC-IV v3.1, MIMIC-III v1.4 and eICU-CRD v2.0**, which are distributed
by PhysioNet under a **credentialed data use agreement that prohibits redistribution**.
Accordingly this repository contains **no patient-level record of any kind**. Specifically
excluded:

| Excluded | What it was | How to regenerate |
|---|---|---|
| `data/field_catalog/cohort_*.parquet` | per-stay cohort tables (patient id, stay id, outcome labels) | `scripts/remote/T1_2_catalog.py` |
| `data_parquet/*.parquet` | the event tables converted from the raw CSVs | `scripts/remote/T1_1_parquet.py` |
| `outputs/T6/hourly_*.parquet` | hourly channel aggregates for the transfer study | `scripts/remote/T6_transfer.py` (stage 1) |
| `data/embed*/`, `data/t5b/` | cached frozen-encoder embeddings (~140 MB) | `scripts/remote/T4_encoder_ladder.py` |
| `refs/` | third-party repositories (LLMatch, SAF, TimeCMA, mimic-code, eicu-code) | clone from their own sources |

To reproduce end to end you need your own PhysioNet credentials and local copies of the
three databases. Everything downstream of that is here.

**What *is* included** is derived metadata and aggregate statistics only: field names,
units, value percentiles, coverage rates, field→concept mappings, and result tables. This
follows the precedent of `mimic-code`, which publishes item identifiers and concept
mappings publicly.

---

## Layout

```
src/schemaalign/     the method
  gates/rules.py       the four deterministic predicates (V_unit, V_type, V_specimen, V_prov)
  match/abstain.py     Eq. (1): the abstention score, AUROC, bootstrap CIs
  match/evalset.py     evaluation-set construction (train/val/test by field-key hash)
  match/baselines.py   exact-name, ontology-only, frozen-encoder baselines
  baselines/           the LLM matcher (LLMatch prompt, verbatim)

scripts/local/       everything that runs on a laptop
  run_table2_final.py         Table 1
  run_placement_graded.py     Table 2(a)  the three consumers of one penalty
  run_paper_tables.py         Table 2(b)  per-dimension ablation
  run_multifamily.py          the three model families
  run_placement_matched.py    paired bootstrap, error decomposition, operating point
  run_contamination_check.py  evidence-provenance stratification
  analyze_expert_validation.py / expert_error_rate.py / apply_expert_corrections.py
  carevue_itemid_leakage.py   the CareVue identifier audit
  vmethod_audit.py            the measurement-method predicate
  make_latex_tables.py        results/tables/*.csv  ->  paper/tables/*.tex
  make_method_figure.py       -> paper/figures/method.{pdf,svg}
  make_paper_constants.py     provenance table for every scalar quoted in the paper
  check_pages.sh              ICASSP page-budget check

scripts/remote/      steps that need the databases and a GPU
data/gold/           the reference standard  (see below)
data/field_catalog/  per-database field catalogues (metadata + aggregates)
data/llm_baseline/   every LLM prompt and completion, verbatim
human_validation/    the blinded expert study: worksheets, instructions, sampling design
results/tables/      32 result tables; every number in the paper traces to one of these
results/figures/     figures
docs/EVIDENCE_LOG.md a 50-entry lab notebook, including the negative results
paper/               LaTeX source (ICASSP spconf style)
tests/               55 unit tests: pytest tests/
```

## The released reference standard

| File | Contents |
|---|---|
| `data/gold/gold_pairs.csv` | 710 field→concept pairs, each with its **evidence provenance** |
| `data/gold/unknown_set_adjudicated.csv` | 2,428 fields adjudicated \textsc{unknown}, with reasons |
| `data/gold/concepts.csv` | the 138-concept catalogue |
| `data/gold/annotator_agreement.json` | κ and its inputs, plus a note on what is *not* reproducible |
| `data/gold/abstain_config.json` | the selected {dimensions, w} and the full calibration grid |
| `data/gold_expert/` | the same standard with every blinded-expert correction applied |
| `results/tables/table5_expert_*.csv` | the expert study: agreement, disagreements, error rate |

## Reproducing the tables

With the reference standard and field catalogues (both included), the alignment results
need no patient data:

```bash
python3 -m pytest tests/ -q
python3 scripts/local/run_table2_final.py
python3 scripts/local/run_placement_graded.py
python3 scripts/local/run_multifamily.py
python3 scripts/local/make_latex_tables.py
```

The LLM matcher outputs are cached verbatim in `data/llm_baseline/`, so these run without
API access. Re-querying the models requires an OpenAI-compatible endpoint and
`SA_LLM_API_KEY` / `SA_LLM_BASE_URL` in the environment.

The downstream transfer study (`scripts/remote/T6_transfer.py`) does need the databases.

## Notes for reviewers

- `docs/EVIDENCE_LOG.md` records the negative results too, including the hypothesis this
  paper started from and abandoned (E31, E34), an arithmetic error we found and fixed in
  our own reference standard (E45, E48), and a predicate that we built, calibrated and
  then did not adopt because the validation split rejected it (E49).
- `results/tables/paper_constants.csv` maps every scalar quoted in the paper to the file
  it comes from.
- `scripts/local/check_pages.sh` enforces the ICASSP page budget mechanically.

## Licence

Code: MIT (see `LICENSE`).
Derived metadata and result tables: CC BY 4.0.
Neither covers the underlying PhysioNet databases, which remain under their own DUA.
