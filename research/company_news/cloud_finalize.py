"""Build the integrated private report; never return empirical values to an LLM."""
from pathlib import Path
import datetime
import hashlib
import json
import numpy as np
import pandas as pd


def table(frame):
    def value(item):
        if pd.isna(item):
            return 'Unavailable'
        if isinstance(item,(float,np.floating)):
            return f'{item:.7g}'
        return str(item).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(map(str,frame.columns))+' |',
        '| '+' | '.join(['---']*len(frame.columns))+' |']+
        ['| '+' | '.join(map(value,row))+' |' for row in frame.itertuples(index=False,name=None)])


def execute(study, source_commit=None):
    root=study.OUT; evaluation=root/'evaluation'; diagnostics=root/'diagnostics'
    assert (evaluation/'manifest.json').exists() and (diagnostics/'manifest.json').exists()
    output=root/'final_report';output.mkdir(exist_ok=False)
    metrics=pd.read_csv(evaluation/'all_metrics_private.csv')
    scenarios=pd.read_csv(evaluation/'all_cost_scenarios_private.csv')
    assert len(metrics)==18 and len(scenarios)==36, 'Incomplete prespecified output grid'
    contrasts=json.loads((evaluation/'paired_contrasts_private.json').read_text())
    contrast_table=pd.DataFrame([{**{key:value for key,value in row.items() if key!='interval_95'},
        'lower_95':row['interval_95'][0],'upper_95':row['interval_95'][1]} for row in contrasts])
    primary=next(row for row in contrasts if row['horizon']==5 and row['target']=='adjusted')
    supported=primary['interval_95'][0]>0
    ic=pd.read_csv(evaluation/'daily_ic_private.csv')
    summaries=[]
    for (horizon,target,model),group in ic.groupby(['horizon','target','model']):
        observed=group.ic.dropna()
        interval=study.paired_interval(observed) if len(observed) else [np.nan,np.nan]
        summaries.append({'horizon':horizon,'target':target,'model':model,'mean_daily_spearman_ic':observed.mean(),
            'lower_95':interval[0],'upper_95':interval[1],'valid_dates':len(observed),'undefined_dates':int(group.ic.isna().sum())})
    ic_summary=pd.DataFrame(summaries)
    ic_summary.to_csv(output/'ic_summary_private.csv',index=False)
    details=json.loads((diagnostics/'diagnostics_private.json').read_text())
    panel_path=diagnostics/'explanatory_panel_private.csv'
    explanatory=table(pd.read_csv(panel_path)) if panel_path.exists() else json.dumps(details['panel'])
    quality=root/'coverage_quality_private.json'
    coverage=table(pd.DataFrame(json.loads(quality.read_text()))) if quality.exists() else 'See the archived private audit and quality gate; no sample counts are fabricated.'
    scenarios_summary=scenarios.groupby('status').size().rename('scenarios').reset_index()
    annual=pd.read_csv(evaluation/'all_years_private.csv')
    paths=pd.read_csv(diagnostics/'all_event_paths_private.csv')
    report=['# Company News: Novelty, Sentiment and Market Response','',
        '**Private research report. Actual findings and figures are not cleared for public dissemination or transmission to an LLM.**','',
        'Wharton Research Data Services (WRDS) was used in preparing this company-news research. This service and the data available thereon constitute valuable intellectual property and trade secrets of WRDS and/or its third-party suppliers.','',
        '## Research question and design','',
        'When do supplier-coded news sentiment, novelty and prior media coverage add information beyond price history? The design compares fixed Ridge ablations B0/B1/B2, develops on 2010–2020 and confirms retrospectively on 2021–2025. All three horizons, both targets and every implementation scenario are retained. Prior coverage is an attention proxy; vendor receipt is an availability proxy. Neither is relabeled as an observed psychological or publication clock.','',
        'RavenPack RPA Dow Jones annual equities tables and quarterly CRSP CIZ support the audited 2010–2025 interval and buffers. The exact private protocol, source tables, links, coverage records and quality checks remain in the archive. Current tickers and present-day index membership are not used to backfill history.','',
        '## Primary incremental-information test','',
        ('The prespecified historical interval supports a positive reduction in MSE from B0 to B2 under this archive design.' if supported else 'The prespecified historical interval does not establish a positive information improvement over B0.'),
        'The sign convention below is MSE(B0) minus MSE(B2), so positive favors B2. The primary endpoint is five-session market-adjusted return with date-equal weighting. Observation-weighted MSE tables use a different weighting convention. These conditional date-block intervals do not establish causality, prospective performance or tradable alpha.','',
        table(contrast_table),'','### All model comparisons','',table(metrics),'',
        '### Daily cross-sectional rank information','',table(ic_summary),'',
        'IC intervals use the same 20-date moving-block / 2,000-draw rule. Secondary intervals are unadjusted for the many reported comparisons. They do not select models or preferred years.','',
        '## Conditional heterogeneity','',explanatory,'',
        'Firm/date fixed effects describe conditional associations. Features are scaled with pre-2021 information. The novelty and coverage interactions are not causal investor-attention measurements. Date-score HAC20 and two-way clustering are descriptive asymptotic diagnostics; unavailable variances are retained as unavailable.','',
        '## Descriptive response paths','',
        '![Private descriptive event paths](../diagnostics/event_paths_PRIVATE.png)','',
        'Offset 0 includes the event-day reaction; it is not earned by the delayed signal strategy. The figure is a fixed middle-coverage view. All 27 predefined novelty/coverage/sentiment combinations and all offsets 0–20, including empty groups and missing paths, are preserved in the full CSV. Overlapping news events remain in the descriptive sample.','',
        table(paths.loc[paths.offset.isin([0,1,5,20])]),'',
        '## Implementation costs, risk and concentration','',table(scenarios_summary),'',table(scenarios),'',
        'The fixed reference is no extra delay, 10 bps on full one-way traded notional and 100 bps annual stock borrowing. Other scenarios do not select a replacement signal. Any missing held return stops that scenario rather than dropping a trade with hindsight. Terminal valid CIZ returns followed by cash and daily-close execution are explicit research assumptions.','',
        '```json',json.dumps(details['economics'],indent=2),'```','',
        'Security contributions reconcile in units of initial capital. Market-only exposure is a limited diagnostic: industry, size, value, liquidity, funding, borrow availability and intraday execution are not established neutralities or observed costs. Inspect security_attribution_private.csv before interpreting concentrated P&L.','',
        '## Annual stability — every confirmation year','',table(annual),'',
        '## Sample and information-quality record','',coverage,'',
        'The loss table separates unknown mapping/feed coverage from observed no-news. These rows need not represent disjoint exclusions; missing prediction targets remain eligible for ranking when contemporaneous baseline features and the calendar allow it. Original annual coverage and mapping audits remain private. Filtered-feed activity does not prove complete delivery.','',
        '## Limits, unsupported claims and next experiment','',
        'This is historical holdout evidence with unverified original score vintages. A favorable statistical endpoint cannot by itself establish causal information arrival or feasible alpha. Negative or unestimable scenarios are retained. A text-model comparison requires the same licensed article corpus; no LM/TF-IDF/BERT ranking is inferred from structured vendor scores.',
        'Next, establish original publication/scoring clocks and revision semantics where available, assess more complete factor and implementation exposures, and obtain explicit dissemination permission before public empirical claims. Human interpretation and rights review remain pending. The existing public FOMC/FX adverse incremental-information conclusion is preserved as a separate study.','',
        '## Traceability','',
        f'Source commit supplied for this archive: {source_commit or "not supplied; inspect source fingerprints"}.',
        'Protocol and development selections precede confirmation scoring. Final input fingerprints below were assembled after execution; they are a reproducibility snapshot and are not falsely presented as a cryptographic pre-fit commitment. Source hashes and earlier extraction records provide additional provenance.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    inputs=[study.ROOT/'ciz_historical_links_private.parquet',study.ROOT/'ciz_market_calendar_private.parquet',
        root/'protocol_v2.json',root/'quality_gate.json',evaluation/'frozen_selection.json']
    inputs+=sorted(root.glob('panel_checked_*.parquet'))+sorted(root.glob('holding_prices_*.parquet'))
    inputs+=sorted(root.glob('news_events_*.parquet'))+sorted(root.glob('prices_*.parquet'))
    fingerprints={}
    for path in inputs:
        if path.exists():
            with path.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            fingerprints[str(path.relative_to(study.ROOT))]={'sha256':digest,'bytes':path.stat().st_size}
    (output/'input_snapshot_private.json').write_text(json.dumps({'recorded':'after execution; not a pre-fit commitment','inputs':fingerprints},indent=2))
    (output/'manifest.json').write_text(json.dumps({'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'research-computations-and-integrated-report-executed; human-interpretation-and-rights-review-pending',
        'source_commit':source_commit,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
        'commercial_data_publication_authorized':False},indent=2))
    print('PRIVATE_INTEGRATED_REPORT_FINISHED',flush=True)
