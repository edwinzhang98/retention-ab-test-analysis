# 01 — Request and Scope

## The request (verbatim, from Growth weekly sync)

> "Did last quarter's ad campaign actually drive conversions? If so, is it worth doubling the budget? Also, we're losing a lot of new users in their first 7 days — which users leave first?"

**Requester:** Growth PM · **Analyst:** Product Analyst, Growth · **Standard deliverables:** an experiment readout and a retention dashboard.

## Clarified analysis questions

| # | PM's question | Analysis question | Decision it informs | Decision owner |
|---|---|---|---|---|
| Q1 | Did the campaign drive conversions? | In the randomized ad-vs-PSA test, is the user-level conversion rate higher for users shown ads, and by how much (absolute pp and relative %, with a 95% CI)? How many *incremental* conversions does that imply? | Keep the campaign running or stop it | Growth PM |
| Q2 | Is it worth doubling the budget? | (a) At what cost per 1,000 impressions does the campaign break even, given an assumed value per conversion? (b) Does the lift look like it keeps growing with more ad exposure, or does it saturate? (c) What can this experiment **not** tell us about a 2× budget? | Scale to 2×, hold, or test 2× first | Growth PM + media buyer |
| Q3 | Does the lift differ by day / hour? (implicit: where to put the money) | Is there statistically reliable heterogeneity in lift by the user's peak ad day / hour, after correcting for multiple comparisons? | Day-parting / budget reallocation | Growth PM + Media buyer |
| Q4 | Which new users leave first? | Among new players, how do Day-1 and Day-7 retention differ by engagement depth (rounds played), by whether they came back on Day 1, and by experiment version? Where is the largest drop? | Which onboarding segment to target first | Growth PM + Game / Onboarding PM |
| Q5 | (Second experiment) Should the progression gate move from level 30 to 40? | Does gate_40 change D7 retention (primary) or D1 retention (guardrail)? Is the experiment itself trustworthy (SRM)? | Ship gate_40 or keep gate_30 | Game PM |

## What would change the decision
- **Q1:** if the 95% CI for the lift includes 0, or the experiment fails its sanity checks (SRM, exposure parity), we can't claim the campaign worked.
- **Q2:** if the breakeven CPM is below what we actually pay, the campaign loses money even with a positive lift. If the lift saturates at high frequency, doubling spend mostly buys wasted impressions.
- **Q3:** reallocation is only justified if heterogeneity survives a formal interaction test *and* multiple-comparison correction. Otherwise "Tuesday looks best" is noise.
- **Q4 / Q5:** a D7 drop with a CI excluding 0 means "don't ship". A failed SRM means the readout can't be certified, and assignment must be investigated before any re-run.

## Outcome notes (added after the analysis; the rules above are kept as written beforehand)
- **Q2(b)** could not be answered with this data. Ads seen is recorded after assignment and tracks how active a user is, so it shows *where* the lift sits (heavy users), not what an extra ad per user does (readout, R2).
- **Q3:** the peak-day signal passed both tests: interaction p = 0.013 (0.038 allowing for the 3 dimensions explored), and Tuesday and Thursday survive Holm. But "peak day" is a user habit recorded after assignment, not a slot we can buy, so the rule above (written with buyable segments in mind) doesn't apply. The signal triggers a randomized delivery-schedule test (R3), not a reallocation.
- **Q4** has no ship decision. It sets the target segment for an onboarding experiment (R6).
- **Q5:** the SRM check gave a WARNING (p = 0.0086), not a FAIL, so the gate result is "not certified" rather than void. The decision rests on the status quo (keep gate_30), no sign of a retention benefit, and a decomposition of the D7 gap (R5). gate_40 players with 30+ rounds played a little more (descriptive).

## Out of scope / not answerable with this data
- **Revenue and ROI:** no revenue or cost fields. Value per conversion and CPM are explicit assumptions (see `assumptions.md`).
- **Time trends / novelty effect:** no dates, only the day-of-week and hour of peak exposure.
- **Long-term retention of converters:** the two datasets are different products with no shared users.

## Timeline
Readout for the next Growth weekly; dashboard kept live for follow-up questions.
