"""Verify three-model ledgers; prepare private report and bounded aggregates."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def verdict(row,absolute_newer=None):
    if row['status']!='computed-conditional-settlement':return 'Not estimable: both complete aligned ledgers are required.'
    if row['lower95']>0:
        message='The unadjusted paired interval supports a positive historical daily net-return increment.'
    elif row['upper95']<0:
        message='The unadjusted paired interval supports a negative historical daily net-return increment.'
    else:
        message='The paired interval includes zero; a positive net-return increment is not established.'
    if absolute_newer is not None and absolute_newer<=0:
        message+=' The newer strategy loses money cumulatively; relative improvement, if any, is loss reduction rather than absolute profitability.'
    return message


def execute(study,input_name='model_strategy_comparison_20261108',output_name='model_strategy_report_20261108'):
    comparison=load('three_model_report_contract','cloud_model_strategy_comparison.py')
    formatter=load('three_model_tables','cloud_finalize.py')
    source=study.OUT/input_name;comparison.verify(source)
    output=study.OUT/output_name
    if output.resolve().parent!=study.OUT.resolve():raise ValueError('Report outside private archive')
    output.mkdir(exist_ok=False)
    results=pd.read_csv(source/'all_324_model_scenarios_PRIVATE.csv')
    pairs=pd.read_csv(source/'all_324_pairwise_comparisons_PRIVATE.csv')
    annual=pd.read_csv(source/'all_annual_results_PRIVATE.csv')
    assert len(results)==len(pairs)==324
    mechanical=[]
    for row in results.itertuples(index=False):
        if row.status!='computed-conditional-settlement':continue
        path=source/f'{row.model}_{row.mode}_delay{row.delay}_cost{row.one_way_bps}_borrow{row.borrow_bps}_PRIVATE.csv'
        ledger=pd.read_csv(path,parse_dates=['date'])
        computed=comparison.summarize(ledger)
        if not np.isclose(computed['total_net'],row.total_net,atol=1e-9):raise ValueError('Saved scenario/ledger mismatch')
        mechanical.append({'model':row.model,'mode':row.mode,'delay':row.delay,'cost':row.one_way_bps,'borrow':row.borrow_bps,'checked':True})
    pd.DataFrame(mechanical).to_csv(output/'independent_ledger_checks_PRIVATE.csv',index=False)
    ref_select=results.delay.eq(0)&results.one_way_bps.eq(10)&results.borrow_bps.eq(100)
    refs=results.loc[ref_select].copy()
    ref_pairs=pairs.loc[pairs.delay.eq(0)&pairs.one_way_bps.eq(10)&pairs.borrow_bps.eq(100)].copy()
    base=refs.loc[refs.multiplier.eq(1.)]
    base_pairs=ref_pairs.loc[ref_pairs.multiplier.eq(1.)]
    reference_diagnostics=json.loads((source/'reference_diagnostics_PRIVATE.json').read_text())
    for key,item in reference_diagnostics.items():
        if item['status']!='computed-conditional-settlement':continue
        mask=refs.model.eq(item['model'])&refs['mode'].eq(item['mode'])
        refs.loc[mask,'market_beta']=item['market_beta']
        refs.loc[mask,'top10_absolute_contribution_share']=item['top10_absolute_contribution_share']
    statements=[]
    for row in base_pairs.to_dict('records'):
        newer=base.loc[base.model.eq(row['newer'])&base.status.eq('computed-conditional-settlement')]
        absolute=float(newer.total_net.iloc[0]) if len(newer) else None
        statements.append({'comparison':row['newer']+' minus '+row['older'],'judgment':verdict(row,absolute)})
    # Only researcher-authored experiment summaries: no dates/security returns,
    # article text, scores, predictions, identifiers or commercial input hashes.
    permitted=['model','multiplier','delay','one_way_bps','borrow_bps','status','reason','total_net',
        'cagr_including_buffer','descriptive_sharpe_zero_rate','max_drawdown','mean_daily_net',
        'annual_one_way_turnover','mean_gross','mean_net_exposure','max_locked_gross']
    pair_fields=['older','newer','multiplier','delay','one_way_bps','borrow_bps','status','reason',
        'daily_mean_net_increment','lower95','upper95','complete_ledger_cumulative_increment',
        'mean_turnover_increment','mean_borrow_increment','mean_trading_cost_increment']
    aggregate_results=results[[c for c in permitted if c in results]]
    aggregate_pairs=pairs[[c for c in pair_fields if c in pairs]]
    aggregate_results.to_csv(output/'aggregate_model_scenarios.csv',index=False)
    aggregate_pairs.to_csv(output/'aggregate_pairwise_comparisons.csv',index=False)
    no_friction=results.loc[results.multiplier.eq(1)&results.delay.eq(0)&results.one_way_bps.eq(0)&results.borrow_bps.eq(0)]
    base_costs=results.loc[results.multiplier.eq(1)&results.delay.eq(0)&results.borrow_bps.eq(100)]
    base_delays=results.loc[results.multiplier.eq(1)&results.one_way_bps.eq(10)&results.borrow_bps.eq(100)]
    prediction_path=study.OUT/'evaluation'/'paired_contrasts_private.json'
    prediction=next(row for row in json.loads(prediction_path.read_text()) if row['horizon']==5 and row['target']=='adjusted')
    # JSON conversion normalizes numpy scalars and missing fields to null.
    records=lambda frame:json.loads(frame.to_json(orient='records',double_precision=15))
    summary={'study':'Company News: Novelty, Sentiment and Market Response',
        'design':'Post-execution supplemental three-model strategy comparison using frozen historical forecasts',
        'forecast_confirmation_years':[2021,2025],'liquidation_buffer_year':2026,
        'holding_rule':'Identical construction rules; actual securities differ with model ranks',
        'reference':{'terminal_quote_multiplier':1,'extra_delay_sessions':0,'one_way_cost_bps':10,'annual_borrow_bps':100},
        'primary_predictive_comparison':prediction,'reference_models':records(refs),
        'reference_pairwise':records(ref_pairs),'zero_friction_base':records(no_friction),
        'base_cost_sweep':records(base_costs),'base_delay_sweep':records(base_delays),'reference_judgments':statements,
        'all_324_model_status_counts':results.status.value_counts().to_dict(),
        'all_324_pairwise_status_counts':pairs.status.value_counts().to_dict(),
        'inference':'Daily net-return difference in 2021–2025; paired 20-session blocks, 2000 draws; unadjusted intervals, no multiplicity-selected claim',
        'cumulative':'Standalone book cumulative return difference includes common 2026 liquidation buffer; not a separately financed overlay',
        'limits':['Terminal-quote cash-equivalent settlement is conditional, not verified cash execution',
            'Different model ranks can change turnover, rejection, risk and factor exposures; no causal information attribution',
            'B1 adds sentiment and news/missingness indicators; B2 adds novelty, interactions and event categories',
            'Historical scoring vintages, funding, impact, borrow availability and actual settlement remain unverified',
            'Own research aggregate output only; no underlying vendor data redistribution license']}
    (output/'aggregate_research_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(2,2,figsize=(13,8))
    for model in comparison.MODELS:
        mode='final-quote-multiplier-1';path=source/f'{model}_{mode}_delay0_cost10_borrow100_PRIVATE.csv'
        if path.exists():
            ledger=pd.read_csv(path,parse_dates=['date']);nav=(1+ledger.net).cumprod();peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
            axes[0,0].plot(ledger.date,nav,label=model);axes[0,1].plot(ledger.date,nav/peak-1,label=model)
        cost=base_costs.loc[base_costs.model.eq(model)&base_costs.status.eq('computed-conditional-settlement')].sort_values('one_way_bps')
        if not cost.empty:axes[1,0].plot(cost.one_way_bps,cost.total_net,marker='o',label=model)
    for i,row in enumerate(base_pairs.to_dict('records')):
        if row['status']!='computed-conditional-settlement':continue
        axes[1,1].plot(np.array([row['lower95'],row['upper95']])*10000,[i,i],color='steelblue')
        axes[1,1].plot(row['daily_mean_net_increment']*10000,i,'o',color='steelblue')
    axes[1,1].set_yticks(range(len(base_pairs)),[r.newer+' - '+r.older for r in base_pairs.itertuples()]);axes[1,1].axvline(0,color='grey',linewidth=.7)
    axes[0,0].set_title('Conditional equity: quote 1x, cost 10 bps, borrow 100 bps')
    axes[0,1].set_title('Drawdown');axes[1,0].set_title('Transaction cost sensitivity; borrow 100 bps');axes[1,0].set_xlabel('One-way bps')
    axes[1,1].set_title('Paired 2021–2025 daily net difference: unadjusted 95%');axes[1,1].set_xlabel('bps per day')
    for axis in [axes[0,0],axes[0,1],axes[1,0]]:
        if axis.lines:axis.legend()
    figure.tight_layout();figure.savefig(output/'three_model_comparison_PRIVATE.png',dpi=170);plt.close(figure)
    annual_reference=annual.loc[annual.delay.eq(0)&annual.one_way_bps.eq(10)&annual.borrow_bps.eq(100)]
    report=['# Company News — Complete Three-Model Strategy Comparison','',
        'Wharton Research Data Services (WRDS) was used in preparing this company-news research. This service and the data available thereon constitute valuable intellectual property and trade secrets of WRDS and/or its third-party suppliers.','',
        '## Design and interpretation','',
        'This is a post-execution supplemental comparison requested after the original B2 outcomes were inspected. It is not a new preregistered or prospective test. All original forecasts, company-days, valuation snapshots and the portfolio engine are frozen. Only the ranking column changes. Identical holding rules do not mean identical securities. No realized-target filter, model-specific source repair or favorable scenario choice is allowed.','',
        'All 324 model scenarios and all 324 pairwise comparisons are retained. The fixed reference is quote 1x, extra delay 0, one-way cost 10 bps and annual borrowing 100 bps. B2 must reproduce every prior B2 ledger before a result is accepted. Unestimable scenarios remain unavailable rather than being reduced to surviving dates.','',
        '## Fixed reference findings','',formatter.table(pd.DataFrame(statements)),'',formatter.table(base),'',formatter.table(base_pairs),'',
        'The paired inferential endpoint is mean daily net-return difference over 2021–2025. Complete-ledger cumulative differences include the common liquidation buffer, and may therefore differ in timing. Intervals use paired 20-session moving blocks and 2000 draws without multiplicity adjustment. A positive point estimate alone is not established incremental profitability. Outperforming another losing strategy may only reduce losses.','',
        '![Private three-model comparison](three_model_comparison_PRIVATE.png)','',
        '## Gross versus costs','',formatter.table(no_friction),'',formatter.table(base_costs),'',
        'Zero-friction and reference books are separately rebalanced simulations, so their cumulative difference is not an additive sum of daily fees. News may change turnover and risk as well as ranking.','',
        '## Execution delay','',formatter.table(base_delays),'',
        '## Terminal-settlement sensitivity and risk','',formatter.table(refs),'',formatter.table(ref_pairs),'',
        'All models use the same exact terminal events and valuations. The 0.5/1/1.5 quote multipliers are operational scenarios, not probability bounds. Existing observed-only reference failures remain in the earlier report. They are not upgraded to verified cash recoveries when conditional ledgers compute. Market beta is descriptive and does not establish factor neutrality.','',
        '## Every reference year, including the separately marked buffer','',formatter.table(annual_reference),'',
        '## Every predefined model scenario','',formatter.table(results),'',
        '## Every predefined paired comparison','',formatter.table(pairs),'',
        '## Mechanical verification','',formatter.table(pd.DataFrame(mechanical)),'',
        'Every computed ledger reconciles gross, borrowing, costs, net and security contributions, rejects unquoted orders, and uses the same forecast clock. B2 outputs match their immutable prior versions. All source/input/output hashes remain in the archive.','',
        '## Relation to the statistical study','',
        'The original five-session adjusted-return MSE comparison is unchanged. Predictive evidence and portfolio differences are separate endpoints. B1 is a sentiment/news-state bundle; B2 adds novelty, interactions and event categories, so neither portfolio increment identifies a single text variable or proves a causal information effect.','',
        '[Original integrated statistical and return-review report](../final_report_return_review_20261106/REPORT_PRIVATE.md). Historical score vintages, borrowing supply, funding, impact, quote execution and actual cash settlement remain limitations. No model is replaced or reselected using this comparison.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'three-model-report-and-independent-ledger-checks-completed',
        'comparison_manifest_sha256':comparison.sha(source/'manifest.json'),'source_sha256':comparison.sha(__file__),
        'aggregate_summary_fields_review_required':True,
        'outputs':{p.name:comparison.sha(p) for p in output.iterdir() if p.is_file()}},indent=2))
    print('THREE_MODEL_REPORT_COMPLETED',flush=True)
