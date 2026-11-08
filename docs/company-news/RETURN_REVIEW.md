# Missing returns: sources, accounting and validation

This follow-up replays frozen forecasts after a held-security return stopped the original implementation. It is a retrospective protocol amendment prompted by an implementation failure. No forecast is refit, no failed trade is deleted, no favorable year is selected and earlier attempts remain immutable. Licensed observations and performance outputs stay in WRDS Cloud.

## Diagnose before filling

A missing return does not mean no price change. The workflow examines four separate questions:

|Question|Evidence|
|---|---|
|Why is the return missing?|CRSP return-missing flag: missing price, corporate-action value, excessive gap, pending/unavailable delisting, new/not-tracked security.|
|Which interval does a finite return cover?|Previous-price date and return-duration flag; a multi-session payoff cannot be applied as a one-session return to changing holdings.|
|Could an order execute?|Positive regular-session close and active trading status. A valuation price or bid/ask average does not grant execution permission.|
|What economic claim survives delisting?|Exact historical PERMNO, last trading price, event/payment dates, distributions, direct delisting return and form of payment.|

CRSP documents the [missingness flags](https://www.crsp.org/wp-content/uploads/appendix/FlagType_RM.html), [duration flags](https://www.crsp.org/wp-content/uploads/appendix/FlagType_RD.html), [trading-status flags](https://www.crsp.org/wp-content/uploads/appendix/FlagType_TS.html) and [delisting payment forms](https://www.crsp.org/wp-content/uploads/appendix/FlagType_PT.html). A stock/mixed consideration is not cash; a final-price quote is not an observed cash payment. The [CIZ guide](https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Guide_Flat_File_Format_2.0.pdf) distinguishes the last trading price, later quote, distribution amount and date on which the delisting return is stored.

## Alternate-source hierarchy

1. Annual CIZ and legacy CRSP, where covered, are compared to the fixed quarterly CIZ snapshot. These are related vendor vintages, not independent economic confirmation.
2. Compustat daily total-return candidates use `(PRCCD / AJEXDI) * TRFD`, complete positive factors, stable USD currency, adjacent exchange sessions and positive volume at both endpoints. A missing factor is never set to one.
3. Exact historical PERMNO–GVKEY/IID links must be valid at both return endpoints. Ambiguity in either direction is quarantined; current tickers are not historical identity. See the [WRDS CCM guide](https://wrds-www.wharton.upenn.edu/documents/402/CRSP-Compustat_Merged_Database_Data_Guide_9efDcmD.pdf).

The initial source check requires at least 20 ordinary observed overlaps and no mismatch beyond absolute tolerance 1e-6 / relative tolerance 1e-5. A separately retained sensitivity uses exactly the latest 20 preceding comparable ordinary returns within 60 calendar days; it cannot search for a passing window or use future overlaps. All provider results remain available. This is a data-quality amendment, not a new forecast confirmation test.

Repairs apply to entire gaps atomically. A lower-priority source cannot partly overwrite another provider's interval. Any observed multi-session recovery must match the compound alternate segment, then be decomposed once to avoid double counting. Alternate prices never replace execution closes. Unknown listing continuity, entitlements and off-exchange identities remain unresolved.

## Three distinct implementation statements

|Version|Meaning and current software status|
|---|---|
|Observed daily returns|The original reference and subsequent observed-only references remain unestimable. They are retained as failures.|
|Certified closed-gap marks|An explicitly stale mark may carry the pre-gap economic claim through a closed missing-price interval. Exact previous-price date, complete duration and later vendor payoff are required. This alone did not establish an estimable reference.|
|Terminal-price settlement sensitivity|Complete reference accounting is conditional on an assumed settlement value at a reconciled final quote. This is not an observed cash payoff, executable liquidation or unconditional strategy validation.|

The terminal sensitivity admits an exact CIZ delisting event only after the last trading price/date reconciles. A finite direct vendor return has priority. Otherwise a positive `PRCF` final price requires no intervening distribution and an endpoint inside the fixed liquidation buffer. The claim remains locked until that endpoint, with explicit stale marks and continued short borrowing. Converting the quote into cash-equivalent value is an assumption; no artificial quoted order is inserted.

Final-quote multipliers 0.5, 1.0 and 1.5 are fixed operational sensitivities, not statistical recovery bounds. They are crossed with all 36 extra-delay / one-way-cost / annual-borrow scenarios: 0/1/2 sessions, 0/5/10/20 bps and 0/100/300 bps. All 108 attempts remain. Three earlier 72-attempt replays also remain, alongside the original 36-attempt study. Buffer-year liquidation is separate from 2021–2025 confirmation.

## Accounting and uncertainty

Unquoted holdings cannot trade and consume the corresponding side's remaining risk budget. Costs apply to one-way traded notional; borrowing continues on short positions. Ledgers must reconcile gross P&L minus borrow and trading cost to net, security contributions to final equity and scenario totals to their saved ledgers. Unresolved held values or incomplete ending liquidation stop estimation. No missing payoff is automatically zero, a complete loss or a generic delisting penalty.

The private report retains annual stability, concentration, descriptive market beta, date-block uncertainty and cost/delay plots under each convention. Intervals are conditional on the settlement rule and exclude uncertainty about actual cash recovery, locates, funding, impact and quote execution. Accounting completion cannot establish implementable alpha or the incremental value of news.

## Software correction retained in the record

The first terminal run encountered a Pandas error involving DataFrame-valued metadata during follow-on reporting. The earlier handler mislabeled this software error as unestimability. The corrected source detaches security attribution from DataFrame metadata immediately, before CSV, annual grouping or diagnostic operations. A separate checked run repeats the same frozen forecast and settlement specification and verifies all saved ledgers and reference security contributions. Both the original run and an unsuccessful cached-report repair attempt remain preserved. Unexpected software errors now propagate instead of being recorded as missing economic values. An invented-input end-to-end test exercises the complete grid, reference diagnostics and delayed terminal accounting.

## Reproduction and release boundary

See the [Cloud source guide](../../research/company_news/README.md) for entry points. Each private run records its exact code, protocol, input snapshots, output fingerprints and failures. Historical code revisions are distinguished from the current reproducible source. The integrated private report preserves the original statistical study and all follow-up comparisons. No empirical metric, security record, data fingerprint, figure or commercial report is released here. Human economic interpretation and dissemination review remain pending.

## Subsequent three-model comparison, 2026-11-08

The original return-review record above is preserved. The [B0/B1/B2 supplement](STRATEGY_COMPARISON.md) now applies these identical saved valuations and book rules to all models, retains all 324 model configurations and 324 paired comparisons, and reproduces every earlier B2 ledger. At the fixed reference all books lose money; the B2−B0 cumulative difference is −1.0808 pp and its paired daily interval contains zero. Quote multipliers do not reverse that reference conclusion. Delayed entry can reverse relative point estimates, also retained. Bounded aggregate experiment tables and a reference figure are now public; source records, forecasts, security/date-level outputs and commercial input hashes remain private.
