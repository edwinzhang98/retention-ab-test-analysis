# Executive summary: ad campaign and new-player retention

**To:** Growth PM · **From:** Product Analyst, Growth · **Date:** 2026-11-03

Full analysis: [report.html](report.html) (opens in any browser). Interactive version: `streamlit run dashboard/app.py`.

## Bottom line

**Keep the ad campaign running at today's budget, but test a bigger budget before doubling it.** The campaign clearly brought in extra conversions, but this test never tried a higher budget, so it can't tell us whether more spend would pay off. **Keep the game's first gate at level 30**, and **focus retention work on bringing new players back the day after they install**, which is where most of them are lost.

## What we found

1. **The campaign worked.** 2.55% of people who saw the ads converted, vs 1.79% of a similar group shown a public-service ad instead: 0.77 more conversions per 100 people (+43%). We're 95% confident the true increase is between 0.59 and 0.94 per 100 people. That is roughly 4,300 extra conversions (likely 3,300 to 5,300) from 14.0 million ad impressions. Only about 30% of the ad group's conversions were caused by the ads; the rest would have happened anyway.
2. **Whether doubling the budget pays off is still unknown.** If a conversion is worth USD 50 (a placeholder; there is no revenue data), the campaign pays for itself as long as 1,000 ad impressions cost less than about USD 15.49 (likely USD 11.83 to 18.85). There are hints of diminishing returns: the 66% of users who saw 20 ads or fewer show no measurable benefit, and the benefit peaks at 51–200 ads and disappears above 200. Heavy users convert more anyway, so this needs a proper test. Shifting spend to particular days or hours isn't supported either.
3. **New players leave early, and the least engaged leave first.** 55% don't come back the day after installing; 19% are back a week later. Almost half (47%) play fewer than 15 rounds, and at most 3.4% of them are back after a week. Players who return on Day 1 are 4.6 times as likely to be back a week later (33% vs 7%). This shows who leaves, not why.
4. **Moving the first gate from level 30 to 40 made one-week retention worse**: 18.2% vs 19.0%, about 82 fewer retained players per 10,000 installs (we're 95% confident the drop is between 0.3 and 1.3 percentage points). The test groups were not split 50/50 as planned, which can signal a technical problem, so the size of the effect is not confirmed; keeping level 30 is the safe choice either way.

## What we recommend

| | Owner | Action | How we'll know it worked |
|---|---|---|---|
| R1 | Growth PM | Keep the campaign at today's budget; keep 5–10% of users seeing public-service ads instead, as an ongoing comparison group. | Extra conversions and cost per extra conversion, monthly; Finance confirms we pay less than break-even. |
| R2 | Growth PM + media buyer | Before doubling, test it: part of the audience gets twice the spend (or a cap on how often they see ads). | Extra conversions per additional USD 1,000. |
| R3 | Media buyer | Keep the current day and hour schedule; the differences are mostly noise. | A planned test, if timing still matters. |
| R4 | Analytics + Engineering | Next ad test: a 50/50 or 80/20 split instead of 96/4, entry timestamps, success and safety metrics agreed up front. | A 10% change becomes detectable with about 181,000 users instead of 1.2 million. |
| R5 | Game PM | Keep the gate at level 30; find the cause of the uneven groups before any re-test. | One-week retention stays at the level-30 baseline (19.0%). |
| R6 | Onboarding PM | Test a Day-1 comeback or onboarding change for players with fewer than 15 rounds. | One-week retention in a randomized test. |

## Risks

- **Money figures rest on a placeholder** (USD 50 per conversion); break-even moves in proportion to the real value.
- **No dates in the data**, so we can't see whether the ad effect wears off.
- **Retention patterns are correlations**: they show where to test, not guaranteed wins.
- **The gate test's uneven groups** leave its effect size unconfirmed (the decision is the safe default regardless).

## Next steps

1. **Finance:** the real value of a conversion and our actual cost per 1,000 impressions (confirms R1).
2. **Analytics + media buyer:** set up the comparison group (R1) and size the budget test (R2).
3. **Engineering:** audit how players were assigned in the gate test (R5).
4. **Onboarding PM + Analytics:** scope the Day-1 experiment (R6).
