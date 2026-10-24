# Resume evidence

These bullets refer only to this independently implemented public-data study. No employer performance, original course/group code, official competition result or trading profit is implied.

## Quantitative research / financial ML

- Engineered a publication-aware financial-text study joining 128 FOMC statements with 4,041 first-published EUR/USD reference observations, separating measurement, release, decision and label-availability clocks.
- Compared price, TF-IDF text and fusion models through eleven development fits and a frozen 42-event historical confirmation period; reported paired event-block uncertainty, calibration and adverse findings.

## Data science / research engineering

- Built an official-source collector with explicit public-domain attribution, raw/normalized source fingerprints, legacy-table validation and an offline packaged dataset.
- Implemented training-only vocabulary/scaling, target-publication purging and model-freeze checks, with reproducible aligned predictions and timing/duplicate diagnostics.

## Result wording

Selected price minus fusion log loss: **-0.00029**, paired 95% interval **[-0.00280, 0.00211]**. The paired interval includes zero: this experiment does not establish incremental text value. Use the measured finding honestly; do not turn a conditional historical comparison into discovered alpha, a Sharpe ratio or a pristine forward holdout. Run counts and test counts describe engineering evidence, not market value.

Evidence: [metrics](../reports/demo/metrics.json), [split and event panel](../reports/demo/event_panel.csv), [frozen choices](../reports/demo/freeze.json), [aligned predictions](../reports/demo/aligned_predictions.csv), [source/data manifest](../financial_text_validation/data/manifest.json), [license scope](../DATA_LICENSE.md).
