# Prespecified methods — company-news v1

## Population and clock

The intended sample is US common stocks, 2010–2025, with at least 400 calendar days of backward history and 22 subsequent exchange sessions. At each prior month-end select up to 1,000 securities by market capitalization, historical share codes 10/11 and exchanges 1/2/3, absolute price at least $5 and prior 20-session average dollar volume at least $1 million. Eligibility is held through the following month. These cutoffs are design choices made before empirical results, not fitted thresholds. Missing listing/delisting observations require explicit treatment; an always-surviving balanced panel is prohibited.

Use the audited exchange-session calendar. Publication, vendor availability and event occurrence have distinct meanings. Admission is at the first session's 23:59:59 New York cutoff at or after both publication and vendor availability; weekend information enters the following session. An event date never substitutes for availability. Missing vendor availability blocks real execution until a documented conservative rule is approved in a new protocol. Vendor historical backfills/revisions may prevent a fully reconstructed point-in-time claim even with timestamps.

Article/entity/event rows first pass a date-valid security mapping. Multiple historical matches are quarantined. Duplicate event labels for the same article/security do not increase article counts or sentiment weight. Conflicting identity/score/time records raise an error. Distinct syndicated article IDs need a vendor story/cluster identifier or a past-only text rule after the audit; the current identity rule does not certify cross-ID story deduplication. Novelty is a separate explanatory feature, not an undocumented duplicate-removal rule.

Build the full eligible security-session grid from the price panel. Distinguish absent news, observed neutral sentiment and missing sentiment using count/indicator columns. Reconcile feed gaps before interpreting zero rows as no news. Missing interior price sessions are rejected rather than bridged by a positional shift. Listings and delistings require explicit endpoints and delisting-adjusted total returns. A historical CUSIP match must use effective dates; today's ticker is insufficient.

## Transparent ablations

All models use Ridge regression with alpha in 0.1/1/10 and identical company-days. B0 contains contemporaneously available 1/5/20-session total returns, 20-session volatility, log capitalization, log dollar volume and the **previous** 20-session average article count. B1 adds daily article-weighted normalized sentiment, a news-present indicator and missing-sentiment indicator. B2 adds mean normalized novelty, sentiment × novelty, sentiment × log(1 + past coverage) and event-category indicators. The normalized adapter must provide directionally consistent sentiment in [-1,1] and novelty in [0,1]; actual transformations depend on audited vendor semantics. Media coverage is a proxy, not a measurement of investors' attention.

The engineering reference treats each sorted event-label combination as a categorical value; categories are learned from training only, and unseen combinations are ignored. A different multi-label representation would require a recorded protocol amendment before real fitting. Imputation, scaling and categorical vocabulary fit only on development data. Explanatory firm/time panel regressions are a separate planned analysis; their significance cannot select the predictive model or establish causality.

## Targets and historical validation

For signal session t, enter at close t+1; the primary 5-session label compounds total returns of t+2 through t+6. One- and twenty-session horizons are secondary. Market-adjusted returns subtract the correspondingly compounded broad-market return, rather than summing daily differences. Event-day paths are descriptive and do not enter signal-following P&L.

Train 2010–2017; select alpha on 2018–2020 validation MSE; confirm on 2021–2025. Labels ending at/after each following boundary are removed from the earlier split. Refit the selected model once on eligible pre-confirmation observations whose labels finish before 2021. No confirmation-based selection of thresholds, models, periods or displayed years. This is retrospective historical holdout evidence, not a prospective forecast.

The primary endpoint is the date-equal-weight mean of paired company-day squared-error differences, B0 minus B2, on five-session market-adjusted labels. Positive favors B2. Model MSE tables additionally show observation-weighted MSE; do not confuse the weighting conventions. Moving date blocks of 20 sessions, 2,000 draws, seed 20261105 give an unadjusted 95% interval. Daily Spearman IC is a companion diagnostic. Report all three horizons, both targets and all three models. Repeated horizons/interactions are not independent discoveries; the bootstrap is conditional on the frozen design and does not refit models.

## Implementation assumptions

Rank the same five-session market-adjusted B2 prediction. Select top/bottom 10%, deterministic security-ID tie breaks, at least one security per leg; skip days with fewer than two nonoverlapping legs. Allocate 1/5 long and 1/5 short capital per daily cohort; each persists for five sessions, producing mature gross exposure 2. The reference ledger rebalances the aggregated cohort target each close and charges drift-induced trades too. Its final liquidation and ramp-up remain in the ledger.

Costs apply to **full absolute one-way traded notional**, not half turnover: 0/5/10/20 bps. Annual short borrowing assumptions 0/100/300 bps accrue over 252 sessions. Extra entry delays 0/1/2 sessions use the same frozen predictions; no cost scenario selects a replacement signal. Desired weights are defined on post-cost equity and a fixed-point calculation reconciles cost, trades and net return. Missing held-security returns stop the ledger. Historical borrow availability, bid/ask, impact, funding, cash interest and actual execution are unverified; this is a daily-close research model.

## Reproducibility and real-data gate

Freeze protocol, dataset/adapter version, input hashes and software revision before empirical fitting. A local snapshot without Git records source hashes and a null commit, rather than fabricating a revision. Every run stores selected settings, every predefined comparison and a fingerprint manifest. Future-news mutations, duplicate rows, mapping validity, training-only transforms, split purging, label arithmetic and cost reconciliation have behavioral tests.

The current command only runs invented inputs. Audit failure cannot be bypassed by renaming those outputs or using a partial course CSV. Real adapters, calendar/feed completeness, revision semantics, delisting treatment and dissemination permission remain explicit acceptance conditions.
