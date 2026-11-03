# Readout: Ad Campaign Test, New-User Retention and the Gate Test

**For:** Growth PM · **Also for:** Onboarding PM (section 2), Game PM (section 3), media buyer · **From:** Product Analyst, Growth · **Date:** 2026-11-03 · Prepared for the Growth weekly

## TL;DR / Decision

| Your question | Short answer | Decision |
|---|---|---|
| Did the ad campaign drive conversions? | **Yes.** Users who saw the ads converted at 2.55%. Users shown a public-service announcement (PSA) in the same slot converted at 1.79%. That is **+0.77 pp (+43%)**, and we're 95% confident the lift is between +0.59 and +0.94 pp. It adds up to about **4,300 extra conversions** (95% range 3,300–5,300), which is only about **30% of the ad group's conversions**: the rest would have happened anyway. | **Keep it running**, with a permanent 5% PSA holdout (R1). |
| Is it worth doubling the budget? | **This test can't tell us.** It compared ads with no ads, not 1× with 2× spend. Essentially all of the extra conversions come from users who saw 36–200 ads (17% of ad users); the two-thirds of users who saw 20 ads or fewer show no lift we could measure. At an assumed USD 50 per conversion, today's campaign pays back only if we pay less than **USD 15.49 per 1,000 impressions**. | **Don't double yet. Test it first:** one group of users gets up to 2× today's ads per person, or a cap on ads per person (R2). |
| Should we move spend to the best days or hours? | **No.** There is a modest day-of-week pattern, but it describes *when users are active*, not slots we can buy. By hour or time of day there is no reliable difference. | **Don't re-plan spend.** If timing matters, pre-register a test that randomizes the delivery schedule (R3). |
| Which new users leave first? | **Players who barely start.** These retention cuts are on the installs of our mobile game, Cookie Cats (the company's other product), because the ad test's data has no retention field. 55.5% of new players don't come back the day after installing. 47% play fewer than 15 rounds in their first two weeks, and only 2.3% of them play on Day 7. Coming back on Day 1 is the earliest strong sign of who stays. | **Test a Day-1 re-engagement change** for new players who play little on their first day (R6). |
| Should the game's first gate move from level 30 to 40? | **No.** Level 40 shows 0.82 pp lower Day-7 retention, but the two test groups were unbalanced from the start, so that number overstates whatever the gate does. The part the gate could explain is about 0.3 pp per install, and even that may not be the gate. There is no sign that level 40 helps retention. | **Keep level 30.** The result is not certified; there is no sign of a retention benefit; level-40 players with 30+ rounds played a little more (descriptive). Fix the test's assignment before any re-test (R5). |

The next experiments also need a less lopsided split, logged dates, guardrails agreed in advance and an automatic daily check that the groups stay the planned size (R4).

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
- 588,101 users in two groups: **564,577 (96%) saw the ads and 23,524 (4%) saw a PSA** in the same slots.
- There is one row per user, and conversion is yes / no. The data doesn't name the conversion event and has no dates.
- The 96/4 split keeps most users on ads during the test, but it makes the test blunt. It could reliably pick up only lifts of **0.26 pp (14%) or more**.
- We assumed the smallest lift worth acting on is 10% (0.18 pp: about 1,000 conversions per 565K-user ad flight, about USD 50K at USD 50). In practice the Growth PM and Finance agree that number before launch. For a lift that size this test had about a **coin-flip chance (51%)** of detecting it; the same users split 50/50 would have had a ≈100% chance.

### Results

| | Saw ads | Saw PSA |
|---|---|---|
| Users | 564,577 | 23,524 |
| Conversions | 14,423 | 420 |
| Conversion rate | **2.55%** | **1.79%** |

**The lift is real.**
- **+0.77 pp (+43%).** We're 95% confident the true lift is between **+0.59 and +0.94 pp** (+30% to +58%). With this many users, a gap this size essentially never appears by chance.
- **About 4,300 extra conversions** (95% range 3,300–5,300) came from 14.0 million ad impressions: roughly 1 extra conversion per 3,200 impressions.
- **Only about 30% of the ad group's conversions were caused by the ads** (95% range 23–37%). Last-touch attribution, which credits the campaign with every conversion by someone who saw an ad, would overstate it **3.3×** (95% range 2.7–4.3×): it would claim all 14,423 conversions instead of about 4,300. Every ad-group user saw at least one ad, so last-touch and any-touch counting give the same answer here.

**Can we trust the test?**
- **The group sizes can't tell us.** The split lands exactly on 96% / 4%, to the nearest user. That most likely means a fixed quota (or a data file trimmed to one): a valid design, but the usual group-size check then passes automatically and proves nothing (detail: DQ check EXP-1).
- **The ad-slot check is reassuring.** Both groups were shown 24.8 ad slots per user on average. The spread differs a little (33% of PSA users vs 30% of ad users saw 1–5; 18% vs 22% saw 11–20), so we use ad counts only to describe patterns, never to adjust the headline result.

**What it's worth (illustrative only).** At an assumed USD 50 per conversion, the extra conversions are worth about USD 217K (95% range USD 166K–264K). The campaign breaks even at up to **USD 15.49 per 1,000 impressions** (95% range USD 11.83–18.85). Below USD 11.83 it pays back even in the pessimistic case.

**Days and hours (where to spend).**
- Users whose busiest ad day was **Tuesday** responded more (+0.95 pp above the other days; 95% range +0.43 to +1.42) and **Thursday** users less (0.74 pp below; 95% range 0.27 to 1.25 below). The signal is modest, and it holds up after allowing for how many cuts we looked at.
- Part of Tuesday's gap is a low control rate: Tuesday's PSA group converted at 1.44% (42 of 2,907 users), one of the lowest rates of the week.
- "Busiest ad day" describes the user's habits (when they happen to use the app), and it was recorded during the test, not chosen in advance. It is not a day we can buy. Moving budget to Tuesdays is a different change, and this test didn't make it.
- **By hour there is no reliable difference.** Grouped into four time-of-day blocks, the apparent difference comes mainly from the night (midnight to 6 am), where the PSA group had just 1 conversion among 735 users. Without the night, no reliable difference remains.

**Number of ads seen (relevant to the budget question).**
- **Two-thirds of users (66%) saw 20 ads or fewer, and they show no lift we could measure** (−0.02 pp; the 95% range runs from −0.14 to +0.09 pp).
- **The next 15% of ad users (21–35 ads) are inconclusive:** +0.27 pp, with a 95% range from −0.21 to +0.66 pp.
- **Users who saw 36–200 ads (17% of ad users) show +1.7 to +7.0 pp, and essentially all of the extra conversions come from them** (98% of the bucket-by-bucket total; see M4a in the metric definitions).
- Above 200 ads we can't tell: the 95% range runs from −4.9 to +4.1 pp, with only 258 PSA users.
- Heavier app users see more ads *and* convert more anyway: in the PSA group, conversion rises from 0.3% (1–5 ads) to 15.5% (200+). So the lift lives in heavy users; this does **not** show that more ads per person cause more lift. It is a lead for a test that varies how many ads each person sees, not a finding.

### Decision

| Question | Decision |
|---|---|
| Keep the campaign? | **Ship: keep it running at the current budget**, with a permanent 5% PSA holdout (a small group that keeps seeing the PSA, so we keep measuring what the ads add). Versus no holdout it forgoes about 226 conversions per 588K-user flight, about USD 11.3K at USD 50 per conversion. This test's 4% PSA group already forgoes about 181, so moving to 5% costs about 45 more (R1). |
| Double the budget? | **Re-test first:** a user-level test in which one group gets up to 2× today's ads per person (the closest stand-in for 2× budget), or a cap on ads per person, before any scale-up. A true budget test needs a split by region (R2). |
| Move spend by day / hour? | **Don't ship.** If timing still matters, pre-register a test that randomizes the delivery schedule, e.g. Tuesday vs. Thursday delivery (R3). |

### Risks & caveats
- **Profit is unconfirmed.** USD 50 per conversion is our assumption, not a Finance number, and the data doesn't say what we pay per 1,000 impressions. Above the breakeven price, the campaign loses money despite the real lift. The breakeven also ignores creative and agency costs.
- **No dates.** We can't tell whether the effect faded as users got used to the ads, or whether the test ran for whole weeks. The +0.77 pp is an average over an unknown period.
- **The planned split isn't documented**, so the fairness of the comparison rests on the equal ad-slot counts, not on the group sizes.
- **Unknown conversion event.** We assume it is the same business event in both groups.
- **Small control group.** There are only 420 PSA conversions, and they drive most of the uncertainty in every range above.
- **Day, hour and ad-count patterns** describe what happened during the test. Don't use them to target users or move budget without a new test.

### Next steps
1. **Finance + Growth PM:** confirm the actual CPM and the margin per conversion; Analytics re-runs the breakeven. The dashboard's Experiment Readout page takes both as inputs.
2. **Eng (ad platform team):** share the experiment's allocation settings, so we can confirm the 96/4 design and whether a quota was used.
3. **Growth PM + Eng:** set up the always-on 5% PSA holdout (R1).
4. **Growth PM + media buyer, with Analytics:** design the 2× ads-per-person or ad-cap test (R2), with users grouped by how active they were *before* the test. Size it with the sample-size calculator on the dashboard's Decision page. The marginal lift of extra impressions may be smaller than the ad-vs-PSA lift. Size this test on a pre-agreed smallest marginal lift worth paying for; the 181K users of the ad-vs-PSA design is a benchmark, not this test's sample size.
5. **Analytics + Eng:** apply the design fixes to the next test (R4).

---

## 2. Which new users leave first?

*These cuts are on the installs of our mobile game, Cookie Cats (one 2017 install cohort), the company's other product: the ad test's data has no retention field. Expect the pattern to carry over to the app, not the exact segment sizes.*

- **Day 1 is the cliff.** 55.5% of installs don't return on Day 1: the biggest drop. A further 29.9 pp of installs return on Day 1 but not on Day 7, so 14.6% return on both (installed 100% → returned on Day 1 44.5% → returned on Day 1 and Day 7 14.6%).
- **14-day play, separate context.** 95.6% of installs play at least one round at some point in their first 14 days (rounds are 14-day totals, so this is not a first-session measure). Overall Day-7 retention is 18.6%, including players who did not return on Day 1.
- **Players who barely start leave first.** Half of new players play 16 rounds or fewer in their first 14 days. 47% play fewer than 15, and only 2.3% of them play on Day 7 (at most 3.4% in any of their round bands), compared with 71% of players with 100+ rounds. Rounds are counted over the first 14 days, which include Day 7, so this *sizes* the early-leaver group. It is not a rule for spotting them on their first day.
- **Coming back on Day 1 is the earliest strong signal of who stays.** Players who return on Day 1 are 4.6× as likely to play on Day 7 (32.8% vs 7.2%). That is an association: it doesn't show that prompting a Day-1 visit would lift Day 7. Illustrative scenario, not a forecast or an upper bound: shifting 1 pp of installs from the non-returners' 7.2% D7 to the Day-1 returners' 32.8% would add about 0.26 pp of D7; R6's real impact must be measured.
- **Few players ever see the first gate.** Only about 37% of installs played 30 or more rounds, roughly what it takes to reach level 30 (a flawless player needs 29).
- **Engagement separates retention far more than the gate version does; this compares associations and does not rank what changing each would achieve.** The two versions differ by 0.8 pp on Day 7, but the groups were unbalanced and about 60% of that gap sits where the gate cannot act; the part that could be the gate is about 0.3 pp, and it may be zero (section 3). Engagement, by comparison, separates Day-7 retention by 70 pp between the least and most engaged players (partly by construction, as above).
- **Data notes.** 87 players who never played a round are flagged as coming back on Day 1 (29 on Day 7), so the flags mean "came back to the game", not "played a round". That is about 0.1% of players, and no conclusion depends on it. The data has no install dates, so all players are treated as one group of new installs. Re-run these cuts on the app's own installs before relying on exact segment sizes.

### Decision
**Test a Day-1 re-engagement change (R6)** for players who barely start (fewer than 15 rounds in 14 days; the real test must target on first-day play, which this data lacks), with Day-7 retention as the primary metric. Lifting Day 7 by 0.5 pp on the 2.3% base (a placeholder target to agree with the Onboarding PM) needs about 31K target players, about 66K installs, at 50/50.

### Next steps
1. **Onboarding PM + CRM:** design the Day-1 re-engagement test (R6), with Day 7 as the primary metric and Day 1 as secondary, and agree the target lift.
2. **Analytics + Eng:** log first-day play, so the test can pick players on their first day rather than on 14-day rounds.

---

## 3. Gate test (Cookie Cats): move the first gate from level 30 to level 40?

### TL;DR / Decision
**Don't ship level 40. Keep the gate at level 30.** The raw comparison shows 0.82 pp lower Day-7 retention for level 40, but the two groups were not comparable: level 40 has about 790 extra installs (789 in the raw log), and the excess sits among players who barely played, long before either gate could matter. About 60% of the raw gap sits where the gate cannot act. The part the gate could explain is about 0.3 pp per install, and even that may not be the gate. There is no sign of a retention benefit from level 40, so we keep the current game and fix the test first. **This result is not certified.** Among players with 30+ rounds, level-40 players played a little more (descriptive).

### What we tested
- **Hypothesis:** moving the first gate (a forced wait, or pay to skip) from level 30 to level 40 keeps more new players coming back on Day 7.
- **Primary metric:** Day-7 retention, the share of new players who play on the 7th day after installing (that day itself, not "any time in the first week").
- **Guardrails:** Day-1 retention, rounds played in the first 14 days, and group sizes matching the planned 50/50 split.
- **Sample:** 90,189 new players were assigned at install: 44,700 to level 30 and 45,489 to level 40. One level-30 player with an impossible 49,854 rounds was left out of the retention numbers as a logging error.

### The raw comparison

| | Level 30 (current) | Level 40 | Difference (95% range) |
|---|---|---|---|
| Day-7 retention | 19.02% | 18.20% | −0.82 pp (−1.33 to −0.31) |
| Day-1 retention | 44.82% | 44.23% | −0.59 pp (−1.24 to +0.06) |
| Rounds played | median 17 | median 16 | −0.04 rounds on average (95% range −1.4 to +1.3) |

Taken at face value, level 40 looks worse on Day 7. It can't be taken at face value, and the other two rows carry the same problem.

### Why the raw gap isn't trustworthy
- **The groups are the wrong size.** Level 40 has about 790 more installs than level 30 (789 in the raw log). A fair 50/50 split produces a gap this large less than 1 time in 100.
- **The excess sits among players who barely played.** Level 40 has a net 762 more players with fewer than 15 rounds, far short of either gate. Among players with 30 or more rounds, the two groups are balanced (16,613 vs 16,656).
- **The same gap shows in play before any gate.** Both versions are identical until level 30, yet level-40 players played slightly less in their first 29 rounds. That is consistent with the point above (more low-play installs in level 40), not independent evidence.
- **A group the gate couldn't affect is slightly lower.** Players with fewer than 30 rounds can't have got past level 30, so they met no gate in either version (bar a rare exception, below), and their retention should match. In level 40 it is slightly lower on Day 7 (−0.33 pp, 95% range −0.65 pp to just below 0), right at the edge of what chance would explain. Such gap as there is comes from players who played 15–29 rounds (−0.87 pp; the two groups are balanced in number there) rather than from players below 15 rounds, where the net excess of installs sits (−0.09 pp), though the data can't tell those two gaps apart. Setting aside the net excess of 762 installs with fewer than 15 rounds only moves it to −0.22 pp.

So the groups were not comparable from the start. The extra low-play installs explain the size gap and the player-mix part of the Day-7 gap, but not the small gap among players who never met a gate, which may be chance.

### What part could be the gate

| Part of the −0.82 pp Day-7 gap (per install) | Size | Could it be the gate? |
|---|---|---|
| Different player mix (more low-play players in level 40) | −0.29 pp | No |
| Players who never met a gate (fewer than 30 rounds) | −0.21 pp | No |
| Players who could meet the gate (30+ rounds) | **−0.32 pp** (95% range −0.71 to +0.07) | Only this part could be, and even it may not be |

- **About 60% of the raw gap sits where the gate cannot act** (the first two rows).
- **−0.32 pp is the part the gate could explain, not an estimate of what the gate does.** Players with 15–29 rounds never met a gate, yet they show a similar Day-7 gap (−0.87 pp, 95% range −1.82 to +0.07) to players with 30+ rounds (−0.87 pp, 95% range −1.94 to +0.20), so even this part may not be the gate. Per 10,000 installs it is about 32 fewer Day-7 players (95% range 71 fewer to 7 more).
- **"Could meet the gate" means 30 or more rounds.** The data has no level field, and every level takes at least one round, so only players with 30+ rounds could have got past level 30. It is an approximation: a level-30 player who reached the gate in exactly 29 rounds and stopped would be counted below 30. Such players are few: level 30 shows no pile-up at exactly 29 rounds (302 players, vs 311 in level 40), and leaving out everyone with 29 rounds, players with 15–28 rounds still show a −0.68 pp Day-7 gap (95% range −1.64 to +0.28).
- **Best case for level 40:** even if none of the roughly 790 extra installs ever came back, level 40 would still trail by 0.50 pp on Day 7 (95% range −1.01 to +0.02), a range that includes zero. No cut shows a Day-7 benefit for level 40.
- **Guardrails.** The raw Day-1 and rounds rows carry the same imbalance as Day 7, so we read them among players who could meet the gate:
  - **Day 1:** no sign of an effect: the part the gate could explain is +0.03 pp per install (95% range −0.29 to +0.35).
  - **Play:** among players with 30+ rounds (who could have reached level 30), level-40 players played a little more (median 75 vs 72 rounds; 83.2% vs 81.4% played at least 40 rounds). It is a descriptive difference: assignment is uncertified and the group is defined by rounds played, so it does not show that level 40 causes more play. These players' Day-7 retention is not higher (−0.87 pp, 95% range −1.94 to +0.20): no sign of a retention benefit.

### Decision
**Keep the gate at level 30 (R5).** It is the current experience, and there is no sign of a retention benefit from level 40. The raw −0.82 pp overstates whatever the gate does: the part the gate could explain is about −0.3 pp per install (about 32 fewer Day-7 players per 10,000 installs; 95% range 71 fewer to 7 more), and even that may not be the gate. Among players with 30+ rounds (who could have reached level 30), level-40 players played a little more (descriptive), so if the Game PM values that, a clean re-test is the way to decide. **The result is not certified** until the imbalance between the groups is explained.

### Risks & caveats
- If level 40 truly makes no difference, keeping level 30 gives up nothing. If it truly helps or hurts a little, only a clean re-test can tell.
- "Could meet the gate" is estimated from rounds played, because the data has no level field (see above).
- The data has no install dates, so we can't check whether the gap changed while the test ran.

### What to fix before any re-test
1. **Eng + Analytics:** find out why level 40 has about 790 extra installs, with the net excess among players who barely played. Most likely assignment or logging added low-play installs to level 40 (or dropped them from level 30); Eng confirms the cause. Compare assignment logs by date, platform, app version and country; check for duplicate or bot installs; check whether players were assigned at install or at first launch, and whether either version failed to log players who left at once.
2. **Game PM, with Analytics:** re-test only if the gate position matters commercially, and only after the fix. Agree in advance the smallest Day-7 change worth acting on; we suggest 0.5 pp per install as a placeholder (about 2.6% of level 30's 19.0%). With the main analysis fixed in advance among players who reach level 30 (both versions are identical until then, so who reaches it can't depend on the gate), that needs about 42K such players: about 114K installs at 50/50. Read over all installs, it needs about 191K. These sizes are for detecting a 0.5 pp drop (a rise of the same size needs up to about 2% more), and they use this test's 37% of installs reaching level 30; re-check that share with the new installs before launch. If the true effect is smaller than 0.5 pp, it would not change the decision.
3. **Analytics + Eng:** run an automatic daily check that the groups stay 50/50, and read Day-1 retention and rounds played as guardrails among players who reach level 30.

---

## Recommendations

| # | Owner | What | Expected impact | How we'll measure | Main risk |
|---|---|---|---|---|---|
| R1 | Growth PM | Keep the campaign at the current budget, with an always-on 5% PSA holdout. | ≈4,300 extra conversions per comparable flight (95% range 3,300–5,300). The holdout forgoes ≈226 conversions per 588K-user flight (≈USD 11.3K at USD 50) vs. no holdout; this test's 4% PSA group already forgoes ≈181. It keeps the real effect measured: last-touch would overstate it 3.3× (95% range 2.7–4.3×). | Extra conversions and cost per extra conversion vs. the holdout, per flight and at least quarterly. | Value per conversion and CPM are unknown: Finance confirms the actual CPM is below USD 15.49 (USD 11.83 at the pessimistic end). One flight's holdout read is about as precise as this test; judge trends over several flights. |
| R2 | Growth PM + media buyer | Don't double blindly; test it. A user-level test where one group gets up to 2× today's impressions per user (the closest stand-in for 2× budget) or a frequency cap; 50/50 or 80/20; users tiered by activity measured *before* the test. A true budget test needs a geo (region) split. | Learn the marginal return before committing ≈2× spend. Today's lift sits in the 17% of ad users who saw 36–200 ads, so the average return may not hold at 2×. | Incremental conversions per extra USD 1K spent. | The marginal lift of extra impressions may be smaller than the ad-vs-PSA lift. Size this test on a pre-agreed smallest marginal lift worth paying for; the 181K users of the ad-vs-PSA design is a benchmark, not this test's sample size. Heavy users may tire of more ads (not measurable here). |
| R3 | Media buyer | Don't re-plan spend by day or hour. If timing matters, pre-register a test that randomizes the delivery schedule (weekday and time slot, e.g. Tuesday vs. Thursday delivery). | Avoids moving money on a pattern that describes users' habits, not slots we buy. | Difference in lift between randomized delivery slots, with its 95% range. | Missing a small real timing effect. |
| R4 | Analytics + Eng | Fix the next test's design: 50/50 or 80/20 split (96/4 had a 51% chance of detecting a 10% lift); log assignment timestamps; pre-register the primary metric, the smallest lift worth acting on, and guardrails (unsubscribe / complaint rate, cost per acquisition); automatic daily group-size check. | The same users at 50/50 would have a ≈100% chance of detecting a 10% lift and could detect 0.10 pp instead of 0.26 pp; timestamps show whether the effect fades. | Chance of detection and smallest detectable lift reviewed at design time; daily group-size check. | A bigger control group means more users miss the ads during the test; logging work for Eng. |
| R5 | Game PM (Eng + Analytics fix assignment) | Keep the first gate at level 30 (no change). The result is not certified. Fix assignment / logging first (level 40 received ≈790 extra installs, with a net excess of 762 among players with fewer than 15 rounds). Re-test only if the gate position matters commercially. | Avoids a change with no sign of a retention benefit. The part of the Day-7 gap the gate could explain is ≈−0.3 pp per install (95% range −0.71 to +0.07; ≈32 fewer Day-7 players per 10,000 installs), and even that may not be the gate. Level-40 players with 30+ rounds (who could have reached level 30) played a little more (median 75 vs. 72 rounds; descriptive). | Any re-test: pre-register a 0.5 pp Day-7 change per install as the smallest change worth acting on (agree with the Game PM); ≈114K installs at 50/50 with the main analysis among players who reach level 30 (≈42K of them), ≈191K if analysed over all installs; daily 50/50 group-size check. | Quoting the raw −0.82 pp would overstate the effect; missing a small real effect either way. |
| R6 | Onboarding PM (with CRM) | Focus retention work on the Day-1 return: a randomized Day-1 re-engagement test for players who barely start (fewer than 15 rounds in 14 days; the real test must target on first-day play, which this data lacks), Day 7 primary. | Targets the biggest drop: 55.5% of installs don't return on Day 1; 47% play fewer than 15 rounds and only 2.3% of them play on Day 7. Illustrative scenario, not a forecast or an upper bound: shifting 1 pp of installs from the non-returners' 7.2% D7 to the Day-1 returners' 32.8% would add about 0.26 pp of D7; R6's real impact must be measured. | Day 7 among targeted players (primary), Day 1 (secondary). Sizing: +0.5 pp Day 7 on the 2.3% base (placeholder target) needs ≈31K target players (≈66K installs) at 50/50. | Rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use first-day play; the play–retention link may not be causal; notification fatigue. |

**Detail behind this memo:**
- dashboard: `streamlit run dashboard/app.py`
- full report: `reports/report.html`
- metric definitions: [`02_metric_definitions.md`](02_metric_definitions.md)
- data-quality checks: [`03_data_quality_checks.md`](03_data_quality_checks.md)
- assumptions: [`assumptions.md`](assumptions.md)

*Revision note (v2/v3): earlier versions read the raw 0.82 pp Day-7 gap as the gate's effect; this one reads only the part the gate could explain, sizes any gate re-test at a change fixed in advance, and turns R2 and R3 into tests that can actually be run.*
