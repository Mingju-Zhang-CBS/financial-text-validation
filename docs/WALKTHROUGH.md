# Walkthrough: a real event through the information clock

Run `python examples/explain_event.py` after installation. The example uses **FOMC-2020-01-29** from the packaged public snapshot.

## One event, not one arbitrary row

|Clock or value|Recorded observation|
|---|---|
|Statement date|2020-01-29|
|Statement conservative availability|2020-01-30 04:59:00+00:00|
|Decision|2020-01-31 04:59:00+00:00|
|Latest available quote measurement|2020-01-24|
|Its release availability|2020-01-28 04:59:00+00:00|
|First later reference quote|2020-01-31|
|20-observation endpoint|2020-03-02|
|Target becomes public|2020-03-10 03:59:00+00:00|
|Entry USD per EUR|1.1082|
|Endpoint USD per EUR|1.1164|

The label is `int(log(endpoint / entry) > 0)`. Here `log(1.1164 / 1.1082) = 0.0073721`, giving target **1**. This is an exchange-rate direction label, not a return on an executable portfolio.

## Reconstruct the input

Filter archived quotes to `available_at <= decision_at`. Sort by measurement date and take the last 61 published observations. Their endpoints yield the 1/5/20/60-observation log-return features; the last 20 daily log changes yield sample volatility. Quote age is measured in calendar days. In this row the 20-observation feature is -0.0052465 and the latest-quote age is 6 days.

The model does not receive the event ID, release URL, future target, endpoint or label availability. Those columns remain in event_panel.csv for audit, while a ColumnTransformer selects only the numeric whitelist and/or policy text. Tests change future/target metadata and verify unchanged predictions.

Text preprocessing removes webpage metadata and voter names, normalizes whitespace and handles exact duplicates in chronological order. TF-IDF learns document counts and its up-to-1,500-feature vocabulary from the fitting partition only. No/not/nor remain available to unigram and bigram features. A coefficient is a regularized association, not a causal policy score.

## Selection and confirmation

The model receives earlier training events whose labels were public before 2017. C values are compared on 2017–2019 validation events, again removing targets not public by 2020. Before confirmation predictions, freeze.json records the five families, settings and event IDs. The selected models refit on eligible earlier data and stay fixed through 2020–2024.

The validation-selected price reference is **price_logistic**. The confirmation log-loss advantage for fusion is -0.00029, with paired interval [-0.00280, 0.00211]. The paired interval includes zero: this experiment does not establish incremental text value. Re-running the package reproduces an exposed historical study; it does not create a fresh holdout.

## Read the uncertainty correctly

For each event, compute price-model log loss minus fusion-model log loss on the **same** label. Resample consecutive four-event blocks with identical indexes for both models, truncate to the original event count, and average each resampled contrast. The 2.5%/97.5% quantiles of 5,000 draws form the interval. This retains some local event dependence; it cannot guarantee coverage under every regime structure.

Inspect calibration_and_years.png, diagnostics.json and exclusions.csv before quoting the headline. Small yearly samples, near-identical wording and a single currency constrain the claim. The source collector's formats and original-vintage limitation are part of the research explanation, not incidental implementation details.
