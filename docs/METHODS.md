# Methods and temporal contract

## Question and population

The study asks whether FOMC statement text adds information beyond lagged EUR/USD price history for the direction of a subsequent 20-observation reference-rate return. It uses one currency and policy-event sampling. It does not estimate the causal effect of policy, immediate announcement surprises, a stock-prediction benchmark or trading returns. EUR/USD here means US dollars per euro: a positive return corresponds to a stronger euro relative to the dollar.

The event universe is every official index link identified as a monetary-policy statement from July 2009 through December 2024, including extraordinary statements. Data discovery rules and target definitions precede model results. H.10 quote archives from January 2009 through February 2025 supply pre-event history and the last events' targets. See protocol.json and DATA_LICENSE.md. This is a locally specified protocol, not an externally registered trial.

## Four distinct clocks

1. The statement has a displayed publication date, checked against its URL. Its modeled availability is the end of that New York day; decision time is 23:59 on the following calendar day. This deliberately avoids depending on a historically variable announcement hour.
2. A daily H.10 quote has a **measurement date** at New York noon. It becomes a feature only after its **actual archived release date**, modeled conservatively at 23:59. The release normally contains the previous business week's observations, and holidays can shift its date. The collector uses listed archive dates, not an assumed Monday calendar.
3. The target's entry quote is the first observed noon rate strictly after decision time. The exit is 20 valid reference observations later, approximately four business weeks. Missing holiday quotes are not filled. This is a delayed prediction problem, not the same-day FOMC market reaction.
4. A training target is usable only after the archived release containing its endpoint has become public. Label-end dates and label-publication times are both recorded. A target ending before a split can still be purged when it was not yet published.

end_of_day localizes in America/New_York before converting to UTC, preserving daylight-saving offsets. event_panel.csv exposes statement availability, decision, latest feature measurement/release, target entry/end and label availability. Source URLs and labels are metadata; the model column whitelist admits only the six price fields and/or body text.

## Vintage construction and exclusions

The downloader supports legacy fixed-width, intermediate HTML and modern H.10 tables. Blank middle holidays must not shift later rates to the wrong date. Year rollover and leap days are checked. Any unsuccessful download or parse prevents a completed dataset; all source errors are recorded for repair. For repeated quote dates, the earliest archived publication is retained.

Events need 61 published historical quotes and 21 subsequent target quotes. The recent price window cannot contain a gap over 14 calendar days; a 20-observation target longer than 40 days is excluded. CSV contracts reject invalid values, timezone-free availability, duplicate keys and supplied target columns. Exact normalized statement bodies keep their first occurrence only. Five-word-shingle Jaccard similarity with the preceding body is recorded; highly similar but changed statements remain because small policy edits can be material. A lower-similarity confirmation diagnostic is reported separately.

## Models and training

- **Historical up frequency:** a train-fitted constant probability, giving a majority-direction baseline at threshold 0.5.
- **Price logistic:** standardized log returns over 1, 5, 20 and 60 published observations; 20-observation daily-return standard deviation; age of the latest available quote.
- **Price histogram gradient boosting:** the same six fields; 100 iterations, three leaf nodes, learning rate 0.05, L2 penalty 1; no automatic early-stopping holdout.
- **Text logistic:** TF-IDF unigrams/bigrams, minimum document count 2, up to 1,500 features, sublinear term frequency and L2 document normalization. The English stop list preserves no/not/nor. No pretrained embeddings or future-trained language model is used.
- **Fusion logistic:** concatenated standardized price features and the same TF-IDF block, with fixed block weights of one. This is a modest feature-fusion baseline, not a tuned multimodal architecture.

Each logistic family tests C in 0.1, 1 and 10. With the fixed prior and gradient controls, this creates eleven development fits. Fit vocabulary, IDF and numeric scaling on training only. Choose each family's setting by validation log loss, breaking a tie toward smaller C; choose the reference price family on the same validation loss. Selection does not use confirmation accuracy, calibration, yearly slices or diagnostics.

Training ends in 2016; validation covers 2017–2019; confirmation covers 2020–2024. Before each later period, purge earlier labels not yet publicly available. After selection, write freeze.json containing settings, cohort and event IDs. Refit selected specifications on the earlier combined data after purging at confirmation start. The model stays fixed throughout confirmation; there is no online refit. The output directory cannot be overwritten.

## Evaluation and uncertainty

All models receive the same event rows and binary target, with threshold fixed at 0.5. Report accuracy, balanced accuracy, log loss, Brier loss, AUC and five-bin expected calibration error. AUC and balanced accuracy are undefined for a one-class slice; small yearly slices and calibration bins are descriptive.

The primary contrast is selected-price log loss minus fusion log loss. Positive means fusion improves probability forecasts. Five thousand paired moving-block resamples use identical event indexes across models, four consecutive events per block and seed 20261023. Accuracy and Brier contrasts accompany the primary measure. Intervals are unadjusted and conditional on the stated search; four-event blocks cannot eliminate arbitrary long-run regime dependence or account for every alternative research idea.

Predetermined diagnostics include all year slices, a single training-label permutation, a lower-similarity subset and a 14-calendar-day extra price-publication delay with frozen model settings. No diagnostic picks a new headline model. A single shuffled fit is not a permutation significance test. Coefficients are associations, potentially reflecting regime and chronology rather than linguistic causality.

## Limits that remain

Historical policy pages retrieved today are not guaranteed original byte-for-byte text vintages; editorial corrections remain a residual data risk. The archived price releases address price revision hindsight. This distinction prevents a blanket claim that the entire dataset is perfectly point-in-time. The sample is small, single-currency and event-conditioned. Noon reference rates lack bid/ask, queues, funding and executable fills; no Sharpe or tradable P&L is reported. Confirmation is historical and becomes exposed after the first run. Repeating the same protocol does not create a new untouched holdout.

A sample purged at the 2017 development boundary can re-enter the final pre-2020 fit once its label has become public. Consequently the final-fit count can exceed retained training plus validation counts; this is a later information set, never confirmation data.
