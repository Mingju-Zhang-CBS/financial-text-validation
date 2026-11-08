# Decisions and hypotheses

A bounded implementation-gap audit is an engineering response to a held-return failure status, not a new prediction specification. It reuses frozen forecasts and the original portfolio function, preserves the failed scenario, and reconciles only the first affected session against source flags. No zero-return imputation, retrospective trade deletion or automatic sample change is authorized by that audit.

Execution update, 2026-11-05: the archive preparation, coverage/holding-label quality gate, frozen predictions and supplementary diagnostics completed in WRDS Cloud. Nullable database floats required an engineering fix, tested on invented nullable values before rerunning the gate. This did not change the research hypothesis or use predictive outcomes to choose a specification. The fixed 10-bps / 100-bps-borrow reference book has a contribution-reconciliation check. Supplementary firm/date inference, event groups and market-exposure diagnostics were specified in code without inspecting empirical outcomes. Their detail supplements the initial high-level plan; it is not claimed as an external preregistration. Final input hashes are a post-execution snapshot.

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
|D009 / 2026-11-05|Review WRDS AI restrictions; keep licensed calculations and findings in the authorized environment, with software-status checks only.|Independent source and synthetic fixtures may be reviewed; no permission inferred for data-derived dissemination.|
|D010 / 2026-11-05|Require a coverage-quality gate to distinguish missing mapping/feed activity from known no-news; obtain holding returns independently of subsequent security classification.|Data-engineering correction before predictive outcomes are inspected; common model rows and entry-time checks must remain explicit.|

|Hypothesis|Prespecified test|Status / alternative explanations|
|---|---|---|
|H1: news adds incremental information|Paired confirmation MSE(B0) minus MSE(B2), same company-days; B1 ablation.|Executed privately; public interpretation pending; coverage, market regimes and score revisions could explain apparent improvement.|
|H2: novelty and past coverage condition sentiment response|Prespecified interactions and separate explanatory panel/event analyses.|Executed privately; public interpretation pending; omitted firm/event risk and changing news composition prevent automatic causal interpretation.|
|H3: improvement has economic value|Fixed five-session overlapping ledger; all costs, borrow and delays.|Observed-only reference failed; conditional terminal settlement sensitivity separately retained; daily closes, impact and short availability can defeat implementability.|

Any amendment records protocol version, reason, affected endpoints, datasets already seen and whether confirmation outcomes were exposed. Do not overwrite unfavorable runs or recast exploratory findings as prespecified.

## Return-review amendments, 2026-11-06

The [complete return-review record](RETURN_REVIEW.md) preserves three 72-attempt replays and a 108-attempt terminal-price sensitivity. Amendments were responses to missing holding values and software failures, without inspecting profitability to choose rules.

|ID|Decision|Timing and status|
|---|---|---|
|D011|Use current CIZ duration, previous-price date, regular-session close and trading status; freeze unquoted positions.|After the original implementation failure; original forecasts unchanged.|
|D012|Compare annual CIZ, legacy CRSP and exact historical CCM-linked Compustat total-return candidates; require complete atomic recovery segments.|Before each amended replay; provider hierarchy and tolerances fixed.|
|D013|Retain a separate latest-20-prior-overlap / 60-calendar-day source-QC sensitivity.|After global-gate failure; no future or selected passing window.|
|D014|Test explicit final-price settlement with 0.5/1/1.5 multipliers only after exact event/price and distribution gates.|After terminal-value failure; operational assumptions, not observed cash or confidence bounds.|
|D015|Detach DataFrame-valued attribution before all follow-on reporting and propagate unexpected software errors.|First terminal report failed; failed attempt and unsuccessful cached repair preserved; corrected run uses the same economic specification.|

No amendment converts this historical period into prospective validation or authorizes public commercial-data findings.

## Three-model strategy supplement, 2026-11-08

|ID|Decision|Relation to inspected outcomes|
|---|---|---|
|D016|Freeze all original forecast rows and the exact v3 engine; replay B0/B1/B2 across three saved terminal valuations and the original cost/borrow/delay grid.|Requested after B2 results were inspected; explicitly post-execution, not preregistered or prospective.|
|D017|Fix B2−B0 as the main supplemental contrast at quote 1x, delay 0, costs 10 bps, borrowing 100 bps; retain B1−B0, B2−B1 and every other configuration.|Fixed before running new B0/B1 outcomes; original predictive endpoint unchanged.|
|D018|Use paired 2021–2025 daily net-return differences with 20-session blocks/2000 draws; retain complete cumulative results including the buffer.|Different inferential/cumulative clocks disclosed; intervals unadjusted for multiplicity.|
|D019|Require exact prior B2 ledger parity and preserve all failures; report relative improvement separately from absolute profitability.|All 324 model scenarios completed and prior B2 reproduced. No positive paired increment established; delay-ordering reversals retained.|
|D020|Publish bounded researcher-authored aggregate experiment tables and negative conclusions with source and invented tests.|No vendor corpus, identifiers, forecasts, saved models, security/date-level ledgers or private input hashes released.|
