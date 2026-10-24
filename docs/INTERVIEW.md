# Interview discussion

## A two-minute explanation

I wanted to measure the incremental information in financial text while keeping availability assumptions inspectable. I chose public FOMC statements and official EUR/USD reference-rate archives with a clear reuse policy. The important engineering issue was that H.10 daily observation dates precede the weekly public release: treating them as same-day features would introduce hindsight.

I built a source-hashed snapshot and event panel with separate publication, decision, feature and label clocks. A small pre-specified experiment compares prior probability, linear and nonlinear price baselines, TF-IDF text and feature fusion. Vocabulary, scaling and settings are learned without confirmation data, and labels crossing a boundary are removed based on their actual public availability. The report keeps uncertainty, unfavorable findings and every year slice.

## Questions to defend

1. Why is the latest observed exchange rate not necessarily an available feature? Explain one archived release containing the prior week's quotes and a holiday shift.
2. Why predict after a full-day delay? Explain the conservative statement-clock choice, later reference-price entry and why the task excludes the immediate announcement reaction.
3. Why purge on label availability instead of just target end? Give a December endpoint whose January release crosses a year boundary.
4. How are leakage and legitimate policy forecasts different? A statement's discussion of future inflation is known text; the subsequently realized exchange rate is not.
5. What does TF-IDF learn? Derive term frequency, training document frequency, normalization and regularized coefficients. Explain why no/not/nor are preserved.
6. What exactly is frozen? The target, universe, feature rules, C grid, selected families/settings, cutoff and event IDs. The five-year confirmation period has no refit.
7. Is a near-duplicate policy statement an independent observation? Discuss boilerplate, economic edits, serial dependence, exact-duplicate handling and the similarity diagnostic.
8. Why report log loss when accuracy is intuitive? Work through a confidently wrong probability, thresholding and calibration.
9. What does the paired interval establish? A conditional historical contrast under a finite block-length assumption; not a universal effect, causal mechanism or corrected search-wide significance level.
10. What would you change next? With lawful data and a new locked period, consider richer price-sensitive targets, multiple currencies, text-difference features and sensitivity to textual vintages. Do not retune against the already exposed confirmation period and call it new out-of-sample evidence.

## Read before using a resume bullet

Open the executed report and explain its actual result. Run examples/explain_event.py; inspect one CSV row and reconstruct its latest available quote and 20-observation target. Then inspect the tests that perturb future prices, inject holdout-only tokens, change target metadata, verify label-publication purging and assert that freeze.json precedes confirmation prediction. Distinguish government-source data, personal code and AI-assisted development.
