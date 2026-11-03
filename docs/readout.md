# Readout: Ad Campaign Test (with the Gate Test and New-User Retention)

**For:** Growth PM · **Also for:** Game PM (section 2), Onboarding PM (section 3), media buyer · **From:** Product Analyst, Growth · **Date:** 2026-11-03 · Prepared for the Growth weekly

## TL;DR / Decision

| Your question | Short answer | Decision |
|---|---|---|
| Did the ad campaign drive conversions? | **Yes.** Users who saw the ads converted at 2.55%. Users shown a public-service announcement (PSA) in the same slot converted at 1.79%. That is **+0.77 pp (+43%)**, and we're 95% confident the lift is between +0.59 and +0.94 pp. It adds up to about **4,343 extra conversions**. | **Keep it running** at the current budget (R1). |
| Is it worth doubling the budget? | **This test can't tell us.** It compared ads with no ads, not 1× with 2× spend. At an assumed USD 50 per conversion, it pays back only if we pay less than **USD 15.49 per 1,000 impressions**. Users who saw the most ads showed no measurable lift. | **Don't double yet. Test 2× first** (R2). |
| Should we move spend to the best days or hours? | **No reliable difference.** The day differences are weak and the hour differences look like noise. | **Don't re-plan** spend (R3). |
| Which new users leave first? | Players who barely play on day one. **47% of installs play fewer than 15 rounds, and at most 3.41% of those are back on Day 7.** Not returning on Day 1 is the clearest warning sign. | **Run a Day-1 onboarding test** (R6). |
| Should the first game gate move from level 30 to 40? | **No.** Level 40 cut Day-7 retention by 0.82 pp (95% range 0.31 to 1.33 pp). The test's user split is off, so treat this as provisional. | **Keep level 30** and investigate the split (R5). |

The next experiments also need a less lopsided split, logged dates and agreed guardrails (R4).

*How to read the numbers: pp = percentage points, so 2.55% vs 1.79% is +0.77 pp, which is +43% in relative terms. A "95% range" is the range we're 95% confident contains the true effect. Differences are computed before rounding.*

---

## 1. Ad campaign: ads vs public-service announcement

### Hypothesis
Showing the campaign's ads instead of a PSA in the same ad slot increases the share of users who convert.

### Metrics
- **Primary:** conversion rate = users who converted ÷ users in the group. Each user counts once.
- **Secondary:**
  - relative lift (%)
  - incremental conversions (the conversions the ads caused)
  - the breakeven price per 1,000 impressions (CPM) at an assumed value per conversion
- **Guardrails (is the test sound?):** the group sizes match the planned split, and both groups were shown the same number of ad slots.
- **Guardrails we'd want but this data lacks:** unsubscribe / complaint rate and cost per acquisition.

### Design & sample
- 588,101 users were split at random. **564,577 (96%) saw the ads; 23,524 (4%) saw a PSA** in the same slots.
- There is one row per user, and conversion is yes / no. The data doesn't name the conversion event and has no dates.
- The 96/4 split keeps most users on ads during the test, but it makes the test blunt: it can only reliably pick up lifts of **0.26 pp or more**. The same users split 50/50 could have picked up 0.10 pp.

### Results

| | Saw ads | Saw PSA |
|---|---|---|
| Users | 564,577 | 23,524 |
| Conversions | 14,423 | 420 |
| Conversion rate | **2.55%** | **1.79%** |

- **Lift: +0.77 pp (+43%).** We're 95% confident the true lift is between **+0.59 and +0.94 pp** (+30% to +58%). With this many users, a gap this size is very unlikely to be chance.
- **About 4,343 extra conversions** (95% range 3,316–5,284) came from 14.0 million ad impressions. That is roughly 1 extra conversion per 3,227 impressions.
- **The ads caused only about 30% of the ad group's conversions.** The other 70% would have happened anyway, so crediting every conversion from an ad-exposed user to the campaign would overstate it about 3.3×.
- **Money (illustrative only):** at an assumed USD 50 per conversion, the extra conversions are worth about USD 217K (95% range USD 166K–264K). The campaign breaks even at up to **USD 15.49 per 1,000 impressions** (95% range USD 11.83–18.85). Below USD 11.83 it pays back even in the pessimistic case.
- **The test looks sound.** The group sizes match 96/4, and both groups saw the same average number of ad slots (24.8 per user). Nobody documented the planned split, though: we inferred 96/4 from the data. That makes the equal-exposure check the more convincing of the two.
- **Days and hours:**
  - The lift ranges from +0.14 pp on Thursday (could be zero) to +1.60 pp on Tuesday, but the evidence that days truly differ is weak.
  - By hour, 8 of 24 hours look better on their own. Checking 24 hours at once will usually turn up one or two by luck, and after allowing for that only 1 hour holds up.
- **Number of ads seen (relevant to the budget question):**
  - Users who saw 20 or fewer ads show almost no lift.
  - Users who saw 51–200 ads show +5.86 to +7.04 pp.
  - Beyond 200 ads there is no measurable lift, but only 258 PSA users are in that group.
  - Heavier app users see more ads, so this pattern mixes "more ads" with "more engaged users". It is a lead for the budget test, not a finding.

### Decision

| Question | Decision |
|---|---|
| Keep the campaign? | **Ship: keep it running at the current budget**, with an always-on 5–10% PSA holdout (a small group that keeps seeing the PSA) (R1). |
| Double the budget? | **Re-test first:** run a randomized 2× budget or frequency-cap test before any scale-up (R2). |
| Move spend by day / hour? | **Don't ship.** If it's still of interest, run a planned day-part test, e.g. Tuesday vs Thursday (R3). |

### Risks & caveats
- **Profit is unconfirmed.** USD 50 per conversion is our assumption, not a Finance number, and the data doesn't say what we pay per 1,000 impressions. Above the breakeven price, the campaign loses money despite the real lift. The breakeven also ignores creative and agency costs.
- **No dates.** We can't tell whether the effect faded as users got used to the ads, or whether the test ran for whole weeks. The +0.77 pp is an average over an unknown period.
- **Unknown conversion event.** We assume it is the same business event in both groups.
- **Small control group.** There are only 420 PSA conversions, and they drive most of the uncertainty in every range above.
- **Day, hour and ad-count patterns** describe what happened during the test. Don't use them to target users without a new test.

### Next steps
1. Finance confirms the actual CPM and the margin per conversion, and we re-run the breakeven. Dashboard page 4 takes both as inputs.
2. Keep a 5–10% PSA holdout always on (R1).
3. Size the 2× budget / frequency-cap test with the sample-size calculator on dashboard page 7 (R2).
4. Apply the design fixes to the next test (R4).

---

## 2. Gate test (Cookie Cats): move the first gate from level 30 to level 40?

### TL;DR / Decision
**Don't ship level 40. Keep the gate at level 30.** Level 40 lowered Day-7 retention. The test's user split is off, though, so the result stays provisional until Eng explains why.

### Hypothesis
Moving the first gate (a forced wait, or pay to skip) from level 30 to level 40 keeps more new players coming back by Day 7.

### Metrics
- **Primary:** Day-7 retention, the share of new players who played on the 7th day after install.
- **Guardrails:** Day-1 retention, rounds played in the first 14 days, and group sizes matching the planned 50/50 split.

### Design & sample
90,188 new players were assigned at random at install. 44,699 kept the gate at level 30 and 45,489 got level 40. One player with an impossible 49,854 rounds was removed as a logging error.

### Results

| | Level 30 (current) | Level 40 | Difference (95% range) |
|---|---|---|---|
| Day-7 retention | 19.02% | 18.20% | **−0.82 pp** (−1.33 to −0.31) |
| Day-1 retention | 44.82% | 44.23% | −0.59 pp (−1.24 to +0.06) |
| Median rounds played | 17 | 16 | about the same |

- **Day 7:** a clear drop: the whole 95% range is below zero. That is roughly 370 fewer Day-7 players per 45,000 installs.
- **Day 1:** could easily be noise. This test couldn't reliably detect a Day-1 change smaller than 0.93 pp.
- **The user split is off:** 45,489 vs 44,699 instead of 50/50. A gap this size happens by chance less than 1 time in 100, so assignment or logging may be broken. Our rule treats this as a warning: we can act on the safe default, but we can't sign off the result.

### Decision
**Don't ship level 40** (R5). Keeping level 30 is the safe, no-change option, and every number points the same way.

### Risks & caveats
- All of level 40's extra players are among players who played fewer than 30 rounds (28,876 vs 28,044), who are unlikely to have reached either gate. Part of the Day-7 gap could therefore come from the split problem rather than the gate.
- Among players with 30+ rounds, level 40 still kept fewer players on Day 7 (43.00% vs 43.87%).
- The data comes from a mobile game in 2017, not our app.

### Next steps
Eng + Analytics trace the split problem through the assignment logs, by date, platform and app version. Re-test only if the gate change is still wanted, with Day-7 retention as the primary metric.

---

## 3. Which new users leave first?

- **Day 1 is the cliff.** 95.57% of new players play at least one round, but only 44.52% come back on Day 1 and 18.61% on Day 7. The biggest single drop, 51.05 pp of installs, comes between the first session and Day 1.
- **Players who barely play leave first.** 47% of installs play fewer than 15 rounds in their first 14 days. At most 3.41% of them are back on Day 7, compared with 71.08% of players who play 100+ rounds.
- **Not returning on Day 1 is the early warning.** Players who return on Day 1 are 4.6× as likely to be back on Day 7 (32.83% vs 7.19%).
- **The gate version matters much less.** It moves Day-7 retention by 0.82 pp, while how much people play separates them by 70.36 pp.
- **Caveat:** rounds are counted over 14 days, which includes Day 7, and players who come back naturally play more. So this tells us *who* to target, not that pushing more rounds will work. That needs a test (R6). These players come from a mobile game standing in for ours, and we should re-run the analysis on our own install cohorts.

---

## Recommendations

| # | Who | What | Expected impact | How to measure | Risk |
|---|---|---|---|---|---|
| R1 | Growth PM | Keep the ad campaign running at the current budget. | ≈ 4,343 extra conversions per comparable flight (95% range 3,316–5,284). | An always-on 5–10% PSA holdout. Track the incremental conversion rate and the cost per incremental conversion. | Value per conversion and CPM are unknown. Finance should confirm that we pay less than the breakeven: USD 15.49 at USD 50 per conversion, or USD 11.83 in the pessimistic case. |
| R2 | Growth PM + media buyer | Don't double blindly. Run a randomized 2× budget or frequency-cap test (50/50 or 80/20 split), sized with the dashboard calculator. | Shows what the *extra* spend returns before we commit to it, and avoids paying for impressions on users who are already saturated. | Extra incremental conversions per extra USD 1K spent (marginal return on ad spend). | Saturation and ad fatigue at high frequency: there was no measurable lift beyond 200 ads. The test also needs enough users to see a 10% change, about 181K at 50/50. |
| R3 | Media buyer | Don't re-plan spend by day or hour yet. If it's still of interest, run a planned day-part test (e.g. Tuesday vs Thursday). | Avoids moving budget on noise. | The lift by day-part in a randomized test, with the comparison chosen in advance. | Chasing noise, or missing a small real day effect. |
| R4 | Analytics + Eng | Fix the next test's design: a 50/50 or 80/20 split instead of 96/4, logged assignment dates and times, and a primary metric and guardrails (unsubscribe / complaint rate, cost per acquisition) agreed before launch. | The same 588K users split 50/50 would detect lifts of 0.10 pp instead of 0.26 pp. A 10% lift needs about 181K users at 50/50 vs about 1.18M at 96/4. Dates show whether the effect fades. | Detectable lift and launch checks, reviewed before the next test starts. | A bigger control group means more users miss the ads during the test. The logging is extra work for Eng. |
| R5 | Game PM | Keep the first gate at level 30. Eng + Analytics investigate the uneven split before any re-test. | Avoids losing ≈ 0.82 pp of Day-7 retention, about 370 fewer Day-7 players per 45,000 installs. | Day-7 retention holds at the level-30 baseline (19.02%), and the split check passes in any re-test. | The drop is provisional. It could be smaller if the split problem inflated it. |
| R6 | Onboarding PM | Focus retention work on the step from first session to Day 1: a Day-1 re-engagement / onboarding test for players with fewer than 15 rounds. | Targets the biggest drop: 47% of installs, of whom at most 3.41% are back on Day 7. The size of the gain is unknown until tested. | A randomized test, with Day-7 retention as the primary metric and Day-1 retention as the secondary. | The rounds–retention link is a correlation, so nudges may not move Day 7. Notification fatigue. |

**Detail behind this memo:**
- dashboard: `streamlit run dashboard/app.py`
- full report: `reports/report.html`
- metric definitions: [`02_metric_definitions.md`](02_metric_definitions.md)
- assumptions: [`assumptions.md`](assumptions.md)
