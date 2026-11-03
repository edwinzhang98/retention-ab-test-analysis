# Executive summary: ad campaign and new-player retention

**To:** Growth PM · **From:** Product Analyst, Growth · **Date:** 2026-11-03

Full analysis: [report.html](report.html) (opens in any browser, works offline). Interactive version: `streamlit run dashboard/app.py`.

## Bottom line

**Keep the ad campaign running, keep a small group of users as an ongoing comparison, and test a bigger budget before doubling it.** The campaign clearly brought in extra conversions, but this test never tried a higher budget, so it can't tell us whether more spend would pay off. **Keep the game's first gate at level 30**: the test of level 40 showed no sign of a benefit, and a setup problem means we can't yet say whether it does any harm. **Focus retention work on bringing new players back the day after they install**, which is where most of them are lost.

## What we found

1. **The campaign worked.** 2.55% of people who saw the ads converted, vs 1.79% of a similar group shown a public-service ad instead: 0.77 more conversions per 100 people (+43%). We're 95% confident the true increase is between 0.59 and 0.94 per 100 people. That is roughly 4,300 extra conversions (likely 3,300 to 5,300) from 14.0 million ad impressions. Only about 30% of the ad group's conversions were caused by the ads; the rest would have happened anyway. Crediting the campaign with every conversion from people who saw an ad would overstate it about 3.3 times.
2. **Whether doubling the budget pays off is still unknown.** If a conversion is worth USD 50 (a placeholder; there is no revenue data), the campaign pays for itself as long as 1,000 ad impressions cost less than about USD 15.49 (likely USD 11.83 to USD 18.85). Almost all the extra conversions (98%) came from the 17% of people who saw many ads (36 to 200), while the 66% who saw 20 or fewer show no measurable benefit. But the people who see the most ads are also the most active and convert more anyway, so this shows where the effect sits, not what extra spend would buy. Only a proper test can answer that. Moving spend to particular days or hours isn't supported either: the one weekday pattern we found reflects users' habits, not a time slot we can buy.
3. **New players leave early, and the least engaged leave first.** 55% don't come back the day after installing, and only 19% play on the seventh day. Almost half (47%) play fewer than 15 rounds in their first two weeks, and at most 3.4% of them come back on day 7. Players who return on Day 1 are 4.6 times as likely to come back on day 7 (33% vs 7%). This shows who leaves, not why.
4. **Moving the first gate to level 40 shows no benefit; whether it does harm is unclear.** The straightforward comparison says level 40 lowered the share of players who came back on day 7 from 19.0% to 18.2%. But the two groups weren't split evenly: the level-40 group got about 790 extra players, almost all of them people who barely played, and even players who never reached either gate came back less often in that group. Once that is taken out, the part the gate itself could have caused is a drop of about 0.3 percentage points, and we're 95% confident it lies between a 0.71-point drop and a 0.07-point gain, so it may be zero.

## What we recommend

| | Owner | Action | How we'll know it worked |
|---|---|---|---|
| R1 | Growth PM | Keep the campaign; keep 5% of users seeing public-service ads instead, as an always-on comparison group. It costs about 226 conversions per 588,000 users (about USD 11,300 at USD 50 each). | Extra conversions and cost per extra conversion, monthly; Finance confirms we pay less than break-even. |
| R2 | Growth PM + media buyer | Before doubling, test it: randomly give part of the audience twice the spend, or a cap on how often they see ads. | Extra conversions per additional USD 1,000. |
| R3 | Media buyer | Keep the current day and hour schedule; if timing still matters, run a planned test of time slots. | The difference between time slots in that test. |
| R4 | Analytics + Engineering | Next ad test: a 50/50 or 80/20 split instead of 96/4, a timestamp for when each user entered the test, success and safety metrics agreed up front, and a running check that the groups stay at their planned sizes. | A 10% improvement becomes detectable with about 181,000 users instead of 1.2 million; the last test had only about a coin-flip chance (51%) of catching it. |
| R5 | Game PM | Keep the gate at level 30. Fix how players are assigned and logged before any re-test, and re-test only if the gate's position matters commercially (it would take about 276,000 installs). | Day-7 retention stays at the level-30 baseline (19.0%); a check confirms the groups come out 50/50. |
| R6 | Onboarding PM | Test a Day-1 comeback or first-session change for new players. | Day-7 retention in a randomized test. |

## Risks

- **Money figures rest on a placeholder** (USD 50 per conversion); break-even moves in proportion to the real value.
- **The budget question is open**: the campaign's effect sits with very active users, so extra spend may buy less than the average suggests.
- **No dates in the data**, so we can't see whether the ad effect wears off.
- **Retention patterns are associations**, and part of the link between rounds played and coming back is built in (both are counted over the same two weeks): they show where to test, not guaranteed wins.
- **The gate test's uneven groups** leave its effect unconfirmed; keeping level 30 is the safe default regardless.

## Next steps

1. **Finance:** the real value of a conversion and our actual cost per 1,000 impressions (confirms R1).
2. **Analytics + media buyer:** set up the 5% comparison group (R1) and size the budget test (R2).
3. **Engineering:** find out why the level-40 group received about 790 extra low-engagement players (R5).
4. **Onboarding PM + Analytics:** scope the Day-1 experiment (R6).
