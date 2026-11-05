# Decisions and hypotheses

|ID / date|Decision|Relation to outcomes|
|---|---|---|
|D001 / 2026-11-05|Extend the existing financial-text repository; preserve executed FOMC/FX findings.|Before company-news data/results.|
|D002 / 2026-11-05|Study structured company news first; raw-text NLP requires the same authorized underlying news.|Before data inspection.|
|D003 / 2026-11-05|Specify 2010–2025, monthly historical top 1,000, $5 price and $1m prior liquidity filters.|Before empirical results; v1 remains unfrozen pending audit.|
|D004 / 2026-11-05|Use Ridge ablations and primary date-equal-weight MSE improvement at five sessions.|Before empirical results.|
|D005 / 2026-11-05|Server authentication failure blocks actual data audit; exercise only invented inputs.|No real-data outcomes inspected.|
|D006 / 2026-11-05|Restore the existing Cloud/Jupyter route; preserve the failed local attempt as history.|Actual access and metadata checked; no forecast comparison inspected.|
|D007 / 2026-11-05|Use audited CIZ interfaces to retain the 2025 endpoint; do not truncate at legacy CRSP's cutoff.|Coverage/schema inspection only.|
|D008 / 2026-11-05|Stage an RPA adapter with receipt-clock caveat, event-to-article collapse and missing novelty preserved.|Protocol amendment remains required before empirical fitting.|

|Hypothesis|Prespecified test|Status / alternative explanations|
|---|---|---|
|H1: news adds incremental information|Paired confirmation MSE(B0) minus MSE(B2), same company-days; B1 ablation.|Untested; coverage, market regimes and score revisions could explain apparent improvement.|
|H2: novelty and past coverage condition sentiment response|Prespecified interactions and separate explanatory panel/event analyses.|Untested; omitted firm/event risk and changing news composition prevent automatic causal interpretation.|
|H3: improvement has economic value|Fixed five-session overlapping ledger; all costs, borrow and delays.|Untested; daily closes, impact and short availability can defeat implementability.|

Any amendment records protocol version, reason, affected endpoints, datasets already seen and whether confirmation outcomes were exposed. Do not overwrite unfavorable runs or recast exploratory findings as prespecified.
