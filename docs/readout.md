# Readout: Ad Campaign Test (with the Gate Test and New-User Retention)

**For:** Growth PM · **Also for:** Game PM (section 2), Onboarding PM (section 3), media buyer · **From:** Product Analyst, Growth · **Date:** 2026-11-03 · Prepared for the Growth weekly

## TL;DR / Decision

| Your question | Short answer | Decision |
|---|---|---|
| Did the ad campaign drive conversions? | **Yes.** Users who saw the ads converted at 2.55%. Users shown a public-service announcement (PSA) in the same slot converted at 1.79%. That is **+0.77 pp (+43%)**, and we're 95% confident the lift is between +0.59 and +0.94 pp. It adds up to about **4,300 extra conversions**, which is only about **30% of the ad group's conversions**: the rest would have happened anyway. | **Keep it running**, with a permanent 5% PSA holdout (R1). |
| Is it worth doubling the budget? | **This test can't tell us.** It compared ads with no ads, not 1× with 2× spend. Almost all of the extra conversions came from heavy app users; the two-thirds of users who saw 20 ads or fewer show no measurable lift. At an assumed USD 50 per conversion, today's campaign pays back only if we pay less than **USD 15.49 per 1,000 impressions**. | **Don't double yet. Test 2× budget or a cap on ads per person first** (R2). |
| Should we move spend to the best days or hours? | **No.** There is a modest day-of-week pattern, but it describes *when users are active*, not slots we can buy. By hour or time of day there is no reliable difference. | **Don't re-plan spend.** If timing matters, run a planned time-of-day test (R3). |
| Which new users leave first? | **Players who barely start.** 55% of new players don't come back the day after installing. 47% play fewer than 15 rounds in their first two weeks, and at most 3.4% of them play on Day 7. Coming back on Day 1 is the earliest strong sign of who stays. | **Test a Day-1 re-engagement change** (R6). |
| Should the first game gate move from level 30 to 40? | **No.** Level 40 shows 0.82 pp lower Day-7 retention, but the two test groups were unbalanced from the start, so that number overstates the likely effect. The part that could be the gate is about 0.3 pp, and it may be zero. Nothing suggests level 40 helps. | **Keep level 30.** Fix the test's assignment before any re-test (R5). |

The next experiments also need a less lopsided split, logged dates, guardrails agreed in advance and an automatic check that the groups stay the planned size (R4).

*How to read the numbers: pp = percentage points, so 2.55% vs 1.79% is +0.77 pp, which is +43% in relative terms. A "95% range" is the range we're 95% confident contains the true value. Differences are computed before rounding.*

---

## 1. Ad campaign: ads vs public-service announcement

### Hypothesis
Showing the campaign's ads instead of a PSA in the same ad slot increases the share of users who convert.

### Metrics
- **Primary:** conversion rate = users who converted ÷ users in the group. Everyone in the data was shown at least one ad or PSA, and each user counts once.
- **Secondary:**
  - relative lift (%)
  - extra conversions: the ones the ads caused
  - the share of the ad group's conversions that are extra
  - the breakeven price per 1,000 impressions (CPM) at an assumed value per conversion
- **Guardrails (is the test sound?):** the group sizes match the planned split, and both groups were shown the same number of ad slots.
- **Guardrails we'd want but this data lacks:** unsubscribe / complaint rate and cost per acquisition.

### Design & sample
- 588,101 users were split at random: **564,577 (96%) saw the ads and 23,524 (4%) saw a PSA** in the same slots.
- There is one row per user, and conversion is yes / no. The data doesn't name the conversion event and has no dates.
- The 96/4 split keeps most users on ads during the test, but it makes the test blunt. It could reliably pick up only lifts of **0.26 pp (14%) or more**. For the smallest lift we'd act on, 10% (0.18 pp), it had about a **coin-flip chance (51%)** of detecting it. The same users split 50/50 would have caught it almost every time.

### Results

| | Saw ads | Saw PSA |
|---|---|---|
| Users | 564,577 | 23,524 |
| Conversions | 14,423 | 420 |
| Conversion rate | **2.55%** | **1.79%** |

**The lift is real.**
- **+0.77 pp (+43%).** We're 95% confident the true lift is between **+0.59 and +0.94 pp** (+30% to +58%). With this many users, a gap this size essentially never appears by chance.
- **About 4,300 extra conversions** (95% range 3,300–5,300) came from 14.0 million ad impressions: roughly 1 extra conversion per 3,200 impressions.
- **Only about 30% of the ad group's conversions were caused by the ads** (95% range 23–37%). A simple last-touch count, which credits the campaign with every conversion by someone who saw an ad, would overstate it **3.3×**: it would claim all 14,423 conversions instead of about 4,300.

**Can we trust the test?**
- **The group sizes can't tell us.** The split is exactly 96.000% / 4.000%: the closest whole number of users to 96%. A random split lands that close only about 3 times in 1,000, so users were most likely assigned to a fixed quota, or the data file was trimmed to one. Either way, the usual group-size check passes automatically and proves nothing.
- **The ad-slot check is reassuring.** Both groups were shown 24.8 ad slots per user on average. The spread differs a little (33% of PSA users vs 30% of ad users saw 1–5; 18% vs 22% saw 11–20), so we use ad counts only to describe patterns, never to adjust the headline result.

**What it's worth (illustrative only).** At an assumed USD 50 per conversion, the extra conversions are worth about USD 217K (95% range USD 166K–264K). The campaign breaks even at up to **USD 15.49 per 1,000 impressions** (95% range USD 11.83–18.85). Below USD 11.83 it pays back even in the pessimistic case.

**Days and hours (where to spend).**
- Users whose busiest ad day was **Tuesday** responded more (+0.92 pp above the other days) and **Thursday** users less (0.76 pp below). The signal is modest, and it holds up after allowing for how many cuts we looked at.
- But "busiest ad day" describes the user's habits (when they happen to use the app), not a day we can buy. Moving budget to Tuesdays is a different change, and this test didn't make it.
- **By hour there is no reliable difference.** Grouped into four time-of-day blocks, the only apparent difference comes from the night (midnight to 6 am), where the PSA group had just 1 conversion among 735 users. Without the night, nothing remains.

**Number of ads seen (relevant to the budget question).**
- **Two-thirds of users (66%) saw 20 ads or fewer, and they show no measurable lift.**
- Users who saw 36–200 ads show +1.7 to +7.0 pp. They are 17% of the ad group but account for **98% of the extra conversions**.
- Above 200 ads we can't tell: the 95% range runs from −4.9 to +4.1 pp, with only 258 PSA users.
- Heavier app users see more ads *and* convert more anyway: in the PSA group, conversion rises from 0.3% (1–5 ads) to 15.5% (200+). So the lift lives in heavy users; this does **not** show that more ads per person cause more lift. It is a lead for a test that varies how many ads each person sees, not a finding.

### Decision

| Question | Decision |
|---|---|
| Keep the campaign? | **Ship: keep it running at the current budget**, with a permanent 5% PSA holdout (a small group that keeps seeing the PSA, so we keep measuring what the ads add). The holdout costs about 226 conversions per 588K-user flight, about USD 11.3K at USD 50 per conversion (R1). |
| Double the budget? | **Re-test first:** a randomized 2× budget or ads-per-person cap test before any scale-up (R2). |
| Move spend by day / hour? | **Don't ship.** If timing still matters, run a planned time-of-day test with the comparison agreed in advance (R3). |

### Risks & caveats
- **Profit is unconfirmed.** USD 50 per conversion is our assumption, not a Finance number, and the data doesn't say what we pay per 1,000 impressions. Above the breakeven price, the campaign loses money despite the real lift. The breakeven also ignores creative and agency costs.
- **No dates.** We can't tell whether the effect faded as users got used to the ads, or whether the test ran for whole weeks. The +0.77 pp is an average over an unknown period.
- **The planned split isn't documented**, so the fairness of the comparison rests on the equal ad-slot counts, not on the group sizes.
- **Unknown conversion event.** We assume it is the same business event in both groups.
- **Small control group.** There are only 420 PSA conversions, and they drive most of the uncertainty in every range above.
- **Day, hour and ad-count patterns** describe what happened during the test. Don't use them to target users or move budget without a new test.

### Next steps
1. Finance confirms the actual CPM and the margin per conversion, and we re-run the breakeven. The dashboard's Experiment Readout page takes both as inputs.
2. The ad platform team shares the experiment's allocation settings, so we can confirm the 96/4 design and whether a quota was used.
3. Set up the always-on 5% PSA holdout (R1).
4. Size the 2× budget / ads-per-person test with the sample-size calculator on the dashboard's Decision page (R2).
5. Apply the design fixes to the next test (R4).

---

## 2. Gate test (Cookie Cats): move the first gate from level 30 to level 40?

### TL;DR / Decision
**Don't ship level 40. Keep the gate at level 30.** The raw comparison shows 0.82 pp lower Day-7 retention for level 40, but the two groups were not comparable: level 40 received about 790 extra players, almost all of whom barely played, long before either gate could matter. Once we set aside what the gate can't have caused, the part that could be the gate is about 0.3 pp, and it may be zero. Nothing suggests level 40 helps, so we keep the current game and fix the test first. **This result is not certified.**

### What we tested
- **Hypothesis:** moving the first gate (a forced wait, or pay to skip) from level 30 to level 40 keeps more new players coming back by Day 7.
- **Primary metric:** Day-7 retention, the share of new players who play on the 7th day after installing (that day itself, not "any time in the first week").
- **Guardrails:** Day-1 retention, rounds played in the first 14 days, and group sizes matching the planned 50/50 split.
- **Sample:** 90,189 new players were assigned at install: 44,700 to level 30 and 45,489 to level 40. One level-30 player with an impossible 49,854 rounds was left out of the retention numbers as a logging error.

### The raw comparison

| | Level 30 (current) | Level 40 | Difference (95% range) |
|---|---|---|---|
| Day-7 retention | 19.02% | 18.20% | −0.82 pp (−1.33 to −0.31) |
| Day-1 retention | 44.82% | 44.23% | −0.59 pp (−1.24 to +0.06) |
| Rounds played | median 17 | median 16 | no difference in the average (−0.04 rounds, 95% range −1.4 to +1.3) |

Taken at face value, this says level 40 costs Day-7 players. It can't be taken at face value.

### Why the raw gap isn't trustworthy
- **The groups are the wrong size.** Level 40 has about 790 more players than level 30. A fair 50/50 split produces a gap this large less than 1 time in 100.
- **The extra players are almost all people who barely played.** 762 of the roughly 790 extra level-40 players played fewer than 15 rounds, far short of either gate. Among players with 30 or more rounds, the two groups are the same size.
- **The groups differed before any gate.** Both versions are identical until level 30, yet level-40 players already played slightly less in their first 29 rounds, by more than chance would explain.
- **A group the gate couldn't affect still shows a gap.** Players who never reached level 30 met no gate in either version, so their retention should match. It doesn't: level 40 is 0.33 pp lower on Day 7 (95% range −0.65 pp to just below 0).

So something other than the gate, most likely how players were assigned or logged, made the level-40 group weaker from the start.

### What part could be the gate

| Part of the −0.82 pp Day-7 gap | Size | Could it be the gate? |
|---|---|---|
| Different player mix (more low-engagement players in level 40) | −0.29 pp | No |
| Players who never reached a gate | −0.21 pp | No |
| Players who could have met the gate | **−0.32 pp** of installs (95% range −0.71 to +0.07) | Yes: the only part that can be |

- Among players who reached level 30, level 40 kept 0.87 pp fewer on Day 7 (95% range −1.94 to +0.20), so the true effect could be zero.
- Even in the most favourable case for level 40, where none of the roughly 790 extra players came back on Day 7, level 40 would still trail by 0.50 pp. Every cut points the same way: no sign of a benefit.
- **Guardrails:** players in both versions played the same amount. On Day 1, a drop of up to 1.2 pp can't be ruled out.

### Decision
**Keep the gate at level 30 (R5).** It is the current experience, nothing suggests level 40 helps, and the direction is negative. The raw −0.82 pp overstates the likely effect. Our best estimate of what the gate itself does is about −0.3 pp of installs, roughly 145 fewer Day-7 players per 45,000 installs, with a 95% range from about 320 fewer to about 30 more. **The result is not certified** until the assignment problem is explained.

### Risks & caveats
- If level 40 truly makes no difference, keeping level 30 costs nothing. If it truly hurts, only a clean re-test can size the harm.
- "Reached level 30" is estimated from rounds played, because the data has no level field. That blurs the estimate for players who met the gate.
- The data comes from a mobile game in 2017, not our app.

### What to fix before any re-test
1. **Eng + Analytics:** find out why level 40 received about 790 extra low-engagement installs. Compare assignment logs by date, platform, app version and country; check for duplicate or bot installs; check whether players were assigned at install or at first launch, and whether either version failed to log players who left at once.
2. **Re-test only if the gate position matters commercially**, after the fix, with an automatic daily check that the groups stay 50/50. Detecting a 0.87 pp change among players who reach the gate needs about 102,000 such players: about 276,000 installs at 50/50.
3. In any re-test, read Day-7 retention among players who reach level 30 as the main result, with Day-1 retention and rounds played as guardrails.

---

## 3. Which new users leave first?

- **Day 1 is the cliff.** 95.6% of new players play at least one round, but only 44.5% come back on Day 1 and 18.6% play on Day 7 (14.6% on both Day 1 and Day 7). The biggest single loss, 51 pp of installs, is between the first session and Day 1.
- **Players who barely start leave first.** Half of new players play 16 rounds or fewer in their first 14 days. 47% play fewer than 15, and at most 3.4% of them play on Day 7, compared with 71% of players with 100+ rounds. Rounds are counted over the first 14 days, which include Day 7, so this *sizes* the early-leaver group. It is not a rule for spotting them on their first day.
- **Coming back on Day 1 is the earliest strong signal of who stays.** Players who return on Day 1 are 4.6× as likely to play on Day 7 (32.8% vs 7.2%). That is an association: it doesn't show that prompting a Day-1 visit would lift Day 7.
- **Few players ever see the first gate.** At most about 37% of installs played the 30 rounds needed to reach level 30.
- **The gate version is a smaller lever.** It moves Day-7 retention by 0.8 pp, against 70 pp between the least and most engaged players. That is small next to engagement, but large enough to decide the gate question.
- **Data notes.** 87 players who never played a round are flagged as coming back on Day 1 (29 on Day 7), so the flags mean "came back to the game", not "played a round". That is about 0.1% of players, and no conclusion depends on it. The data has no install dates, so all players are treated as one group of new installs. It is a mobile game standing in for our app: re-run these cuts on our own installs before relying on exact numbers.

---

## Recommendations

| # | Who | What | Expected impact | How to measure | Risk |
|---|---|---|---|---|---|
| R1 | Growth PM | Keep the ad campaign running at the current budget, with an always-on 5% PSA holdout. | ≈ 4,300 extra conversions per comparable flight (95% range 3,300–5,300). The holdout costs ≈ 226 conversions per 588K-user flight (≈ USD 11.3K at USD 50) and keeps the campaign's real effect measured: last-touch counting would overstate it 3.3×. | Extra conversions and cost per extra conversion against the holdout, every flight. | Value per conversion and CPM are unknown: Finance confirms we pay less than USD 15.49 per 1,000 impressions (USD 11.83 in the pessimistic case). A 5% holdout gives a read about as precise as this test, so judge trends over several flights. |
| R2 | Growth PM + media buyer | Don't double blindly. Run a randomized 2× budget or ads-per-person cap (frequency cap) test, with a 50/50 or 80/20 split, sized with the dashboard calculator. | Shows what the *extra* spend returns before we commit to it. 98% of today's extra conversions come from the 17% of ad-group users who saw 36–200 ads, so the test should report heavy and light users separately, grouped by activity from before the test. | Extra conversions per extra USD 1K spent (marginal return on ad spend). | The test needs enough users: about 181K at 50/50 to see a 10% change, vs about 1.18M at 96/4. Heavy users may tire of more ads, which this test couldn't measure. |
| R3 | Media buyer | Don't re-plan spend by day or hour. If timing matters, run a planned time-of-day test with the comparison agreed in advance. | Avoids moving budget on a pattern that describes when users are active, not what we can buy. | Lift by bought time slot in a randomized test. | Missing a small real timing effect. |
| R4 | Analytics + Eng | Fix the next test's design: a 50/50 or 80/20 split instead of 96/4; logged assignment dates and times; a primary metric and guardrails (unsubscribe / complaint rate, cost per acquisition) agreed before launch; an automatic daily check that group sizes match the plan. | At 96/4 this test had a 51% chance of detecting a 10% lift; the same users split 50/50 would have caught it almost every time, and would detect lifts of 0.10 pp instead of 0.26 pp. Dates show whether the effect fades. | Detectable lift and launch checklist reviewed before the next test starts; the group-size check runs daily. | A bigger control group means more users miss the ads during the test. The logging is extra work for Eng. |
| R5 | Game PM | Keep the first gate at level 30 (no change). Eng + Analytics fix assignment / logging first (level 40 received about 790 extra low-engagement installs). Re-test only if the gate position matters commercially. | Avoids a change with no sign of benefit. If level 40 does hurt, the likely size is about 0.3 pp of installs (≈ 145 Day-7 players per 45,000 installs), and it may be zero. | Any re-test: about 276K installs at 50/50, a group-size check that passes, and Day-7 retention among players who reach level 30 as the main result. | Quoting the raw −0.82 pp would overstate the effect. A Day-1 drop of up to 1.2 pp can't be ruled out. |
| R6 | Onboarding PM | Focus retention work on the step from first session to Day 1: a randomized Day-1 re-engagement test for new players who play little on their first day, with Day-7 retention as the primary metric. | Targets the biggest drop: 47% of installs play fewer than 15 rounds, and at most 3.4% of them play on Day 7. The size of the gain is unknown until tested. | Day-7 retention (primary) and Day-1 retention (secondary) in the test. | Rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use first-day play. The link between playing more and staying may not be causal. Notification fatigue. |

**Detail behind this memo:**
- dashboard: `streamlit run dashboard/app.py`
- full report: `reports/report.html`
- metric definitions: [`02_metric_definitions.md`](02_metric_definitions.md)
- assumptions: [`assumptions.md`](assumptions.md)

*Revised 2026-11-03: the gate-test section now separates what the gate could have caused from the assignment problem, and the earlier reading of a 0.82 pp drop caused by level 40 is withdrawn. The ad section adds the share of conversions the ads caused, the holdout cost and the chance this test had of detecting a 10% lift.*
