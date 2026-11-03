# 00 — Project Plan (one page)

**Owner:** Product Analyst, Growth · **Stakeholder:** Growth PM · **Written:** 2026-11-03

## Data
| Use | Dataset | Rows | Key fields |
|---|---|---|---|
| Main A/B story | Marketing A/B (Kaggle `faviovaz/marketing-ab-testing`, 2021) | 588,101 users | `test group` (ad / psa), `converted`, `total ads`, `most ads day`, `most ads hour` |
| Retention + 2nd A/B | Cookie Cats (Kaggle, 2017) | 90,189 players | `version` (gate_30 / gate_40), `sum_gamerounds`, `retention_1`, `retention_7` |

Why both: real user-level A/B data is rare in public. Marketing A/B is newer and less worked-over but has no retention field. Cookie Cats has retention but is a widely used teaching dataset. So it is used for retention and as a second, method-comparison experiment.

Raw data is read from `~/projects/data-projects/datasets/...` via `config.yaml` (overridable with `.env`), never committed.

## Analysis outline
1. **Scope** (`01_request_and_scope.md`): turn the PM's three questions into decisions.
2. **Metric definitions** (`02_metric_definitions.md`): conversion rate, absolute / relative lift, incremental conversions, D1 / D7 retention, SRM, MDE.
3. **Data quality** (`03_data_quality_checks.md`): row reconciliation, key uniqueness, nulls, value domains, outliers (49,854-round player), time coverage (no timestamps, which matters for novelty-effect claims).
4. **Retention (Cookie Cats)**: D1 / D7 overall, the D1→D7 funnel, segments by engagement depth (rounds bucket relative to the gate at level 30 / 40), first-day return status, and version.
5. **Ad experiment (Marketing A/B)**: hypothesis, primary / secondary / guardrail metrics, SRM vs the intended 96/4 split, balance of the post-assignment exposure fields, two-proportion z-test + Newcombe CI + count-level bootstrap, power / MDE (and what the 96/4 split costs us), incremental conversions and breakeven CPM, lift by exposure bucket (where the lift lives, for the "double the budget?" question; not a frequency curve).
6. **Heterogeneity**: lift by `most ads day` / `most ads hour` / daypart / exposure with one interaction test per dimension, then segment-vs-rest contrasts with Holm / BH correction.
7. **Gate experiment (Cookie Cats)**: same readout template. It gets an SRM *warning* (p = 0.0086), located by rounds played; a decomposition of the D7 gap separates what the gate could explain from the imbalance, and the result is handled as uncertified.
8. **Decision + recommendations**: each item states who, what, expected impact, how to measure, and risk.

## Expected outputs
`dashboard/app.py` (7-page Streamlit), `reports/report.html` (standalone), `docs/readout.md`, an executive summary, SQL (DuckDB), 3 notebooks plus HTML exports, and a README with screenshots. `python run.py` (or `make all`) rebuilds everything.

## What I borrow from reference projects
- The mainstream recipe (chi-square / z-test, lift, bootstrap) from the top Kaggle notebooks on both datasets (e.g. `adhamtarek147/a-b-testing-analysis`, `mursideyarkin/mobile-games-ab-testing-with-cookie-cats`).
- Bootstrap / permutation framing from GitHub `xxtofff/Marketing-AB-Testing`.

## What I add (what the references usually skip)
- SRM checks with a two-level rule (FAIL if p < 0.001, WARNING if p < 0.01). Cookie Cats gets a **WARNING**, located by rounds played; a negative control (players who never met a gate) is borderline but points the same way. The ad test's 96.000 / 4.000 split is most likely a fixed quota, so its SRM "pass" is uninformative.
- Power / MDE, including how much sensitivity the 96/4 split gives up versus 50/50.
- Treating `total ads`, `most ads day` and `most ads hour` as **post-assignment** variables: their distributions differ by arm, so heterogeneity is labelled exploratory and is never used as a covariate.
- Two further rounds of methods checks after the first pass. The first added segment-vs-rest contrasts, power at the smallest lift worth acting on (instead of post-hoc power), negative controls, and the "lift lives in heavy users" framing in place of a saturation claim. The second led to reading the gate's D1 and engagement guardrails where the gate can act, sizing the re-test at a pre-registered threshold, and calling −0.32 pp "the part the gate could explain" rather than an estimate.
- One interaction test per dimension, then segment-vs-rest contrasts with multiple-comparison correction, instead of eyeballing 7 + 24 segment lifts.
- Converting lift into incremental conversions and a breakeven CPM, with the value per conversion as an explicit, adjustable assumption (the data has no revenue).
- An answer to "double the budget?" that says what the data **can't** tell us, and proposes the test that would.
- A stakeholder readout, metric definitions, a DQ log and an assumptions log.

## Judgement calls
- **No extra web search**: `reference-projects.md` already covers mainstream practice; the gaps are clear.
- **Outlier**: drop the single player with 49,854 rounds (≈3,561 rounds/day over 14 days, so not humanly plausible). Retention proportions are unaffected, and the sensitivity check is in the DQ doc.
- **Value per conversion**: the data has no revenue. Use **USD 50 as an illustrative default**, labelled everywhere and adjustable in the dashboard. The headline business number is *incremental conversions*, not dollars.
- **Optional CTR branch** (Avazu / Criteo): not done. The prompt says to do it only when applying to ad-tech roles.
- **Cookie Cats SRM warning**: not a stop condition. The decision (keep gate at 30) is the conservative default either way; the readout says the result can't be certified until assignment is debugged.
