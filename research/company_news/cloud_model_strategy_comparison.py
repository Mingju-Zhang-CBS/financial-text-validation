"""Post-execution, frozen-forecast B0/B1/B2 strategy comparison in WRDS Cloud.

Uses the unchanged v3 book and the exact three saved v4 valuation snapshots.
No retraining, outcome-based security filtering, new quote, or source repair.
"""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd

MODELS=('B0','B1','B2')
PAIRS=(('B0','B1'),('B1','B2'),('B0','B2'))
ESTIMATION_FAILURES=('Unresolved held return','Invalid total return','Equity exhausted',
                     'Unliquidated ending positions','No executable turnover')
ENGINE_SHA='03932a9fe6fde33118e9169d63eb6b1aa086e3edf1812de69af5c578e02b10a2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    for name,expected in manifest['outputs'].items():
        if sha(folder/name)!=expected:raise ValueError('Changed immutable research output')
    return sha(folder/'manifest.json')


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def ranking_input(predictions,model):
    if model not in MODELS:raise ValueError('Unknown model')
    if predictions.duplicated(['date','permno']).any():raise ValueError('Duplicate forecast key')
    if not np.isfinite(predictions[list(MODELS)].to_numpy(dtype=float)).all():
        raise ValueError('Forecasts must share every company-day; no model-specific deletion')
    # B2 is the unchanged engine's ranking-column interface, not a refitted score.
    return predictions[['date','permno',model]].rename(columns={model:'B2'}).copy()


def summarize(ledger):
    if ledger.empty or ledger.date.duplicated().any():raise ValueError('Invalid ledger clock')
    if not np.isfinite(ledger.net).all():raise ValueError('Nonfinite ledger return')
    if not np.allclose(ledger.net,ledger.gross-ledger.borrow-ledger.trading_cost,atol=1e-10):
        raise ValueError('Gross/cost/borrow/net reconciliation failure')
    if ledger.unquoted_traded_notional.abs().max()>1e-9:raise ValueError('Unquoted execution found')
    nav=(1+ledger.net).cumprod();peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
    years=(ledger.date.max()-ledger.date.min()).days/365.25
    deviation=float(ledger.net.std(ddof=1))
    return {'total_net':float(nav.iloc[-1]-1),'cagr_including_buffer':float(nav.iloc[-1]**(1/years)-1) if years>0 else np.nan,
        'descriptive_sharpe_zero_rate':float(np.sqrt(252)*ledger.net.mean()/deviation) if deviation>0 else np.nan,
        'max_drawdown':float((nav/peak-1).min()),'mean_daily_net':float(ledger.net.mean()),
        'annual_one_way_turnover':float(252*ledger.one_way_turnover.mean()),
        'max_gross':float(ledger.gross_exposure.max()),'mean_gross':float(ledger.gross_exposure.mean()),
        'mean_net_exposure':float(ledger.net_exposure.mean()),'max_locked_gross':float(ledger.locked_gross_exposure.max())}


def bootstrap_weights(length,draws=2000,seed=20261105):
    if length<=0:raise ValueError('Empty inference clock')
    rng=np.random.default_rng(seed);block=min(20,length)
    weights=np.empty((draws,length),dtype=float)
    for draw in range(draws):
        starts=rng.integers(0,length-block+1,size=int(np.ceil(length/block)))
        indices=np.concatenate([np.arange(start,start+block) for start in starts])[:length]
        weights[draw]=np.bincount(indices,minlength=length)/length
    return weights


def paired(older,newer,weights):
    if not older.date.equals(newer.date):raise ValueError('Unaligned strategy clocks')
    # Confirmation returns are the inferential endpoint. Buffer cash flows remain
    # in complete-ledger cumulative results and are separately disclosed.
    confirmed=older.date.dt.year.le(2025)
    difference=(newer.loc[confirmed,'net']-older.loc[confirmed,'net']).to_numpy()
    if weights.shape[1]!=len(difference):raise ValueError('Bootstrap clock mismatch')
    interval=np.quantile(weights@difference,[.025,.975])
    return {'daily_mean_net_increment':float(difference.mean()),'lower95':float(interval[0]),'upper95':float(interval[1]),
        'complete_ledger_cumulative_increment':float((1+newer.net).prod()-(1+older.net).prod()),
        'mean_turnover_increment':float(newer.one_way_turnover.mean()-older.one_way_turnover.mean()),
        'mean_borrow_increment':float(newer.borrow.mean()-older.borrow.mean()),
        'mean_trading_cost_increment':float(newer.trading_cost.mean()-older.trading_cost.mean())}


def execute(study,output_name='model_strategy_comparison_20261108'):
    output=study.OUT/output_name
    if output.resolve().parent!=study.OUT.resolve():raise ValueError('Comparison outside private archive')
    output.mkdir(exist_ok=False)
    previous=study.OUT/'terminal_sensitivity_v4_checked'
    hashes={'previous_manifest':verify(previous),'evaluation_manifest':verify(study.OUT/'evaluation')}
    prediction_path=study.OUT/'evaluation'/'predictions_private.parquet'
    old_protocol=json.loads((previous/'protocol.json').read_text())
    if sha(prediction_path)!=old_protocol['prediction_sha256']:raise ValueError('Frozen forecasts changed')
    if sha(Path(__file__).with_name('implementation_v3.py'))!=ENGINE_SHA:raise ValueError('Portfolio engine changed')
    protocol={'id':output_name,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'timing':'Post-execution supplemental strategy ablation; original B2 outcomes already inspected; not preregistered or prospective',
        'request':'Replay B0/B1/B2 with exactly the same portfolio-construction, quote, cost and terminal-settlement rules',
        'frozen_forecasts':sha(prediction_path),'unchanged_engine_sha256':ENGINE_SHA,
        'models':list(MODELS),'terminal_multipliers':[.5,1.,1.5],
        'scenario_grid':{'delay':[0,1,2],'one_way_bps':[0,5,10,20],'borrow_bps':[0,100,300]},
        'reference':{'multiplier':1.,'delay':0,'one_way_bps':10,'borrow_bps':100},
        'main_supplemental_contrast':'B2 minus B0 paired mean daily net return, 2021–2025; secondary B1-B0 and B2-B1',
        'uncertainty':'Same-date 20-session moving blocks, 2000 draws, seed 20261105; all contrasts unadjusted for multiplicity',
        'cumulative_endpoint':'Complete common ledger including predeclared 2026 liquidation buffer; also report all annual rows',
        'holding_rule':'Same top/bottom deciles and five-session overlapping cohorts; actual selected securities differ by model ranking',
        'common_sample':'All original forecast company-days, including unavailable realized targets; reject incomplete model scores rather than silently filter',
        'missing_rule':'Unresolved held value stops entire scenario; do not truncate to surviving dates, delete trades or repair just one model',
        'regression_gate':'Every computed B2 ledger must reproduce the matching prior complete B2 ledger',
        'scope':'Standalone research book return differences, not causal information effects or a separately funded tradable overlay',
        'input_manifests':hashes,'source_sha256':sha(__file__)}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    engine=load('frozen_comparison_book','implementation_v3.py')
    predictions=pd.read_parquet(prediction_path)
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')].reset_index(drop=True)
    scores={model:ranking_input(predictions,model) for model in MODELS}
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet').sort_values('date')
    calendar=pd.DatetimeIndex(market.loc[market.date.ge(predictions.date.min()),'date'])
    if calendar.duplicated().any() or not calendar.is_monotonic_increasing:raise ValueError('Invalid common calendar')
    weights=bootstrap_weights(int((calendar.year<=2025).sum()))
    scenarios=[];annual=[];comparisons=[];mechanical=[];reference={}
    for multiplier in [.5,1.,1.5]:
        mode=f'final-quote-multiplier-{multiplier:g}'
        valuation_path=previous/(mode+'_valuation_PRIVATE.parquet')
        hashes[mode]=sha(valuation_path)
        prices=pd.read_parquet(valuation_path)
        for delay in [0,1,2]:
            # A separate target matrix for each model is essential. Only immutable
            # price inputs are common; never reuse another model's prepared scores.
            states={model:engine.prepare(scores[model],prices,calendar,delay) for model in MODELS}
            for cost in [0,5,10,20]:
                for borrow in [0,100,300]:
                    ledgers={};statuses={}
                    for model in MODELS:
                        key={'mode':mode,'multiplier':multiplier,'delay':delay,'one_way_bps':cost,'borrow_bps':borrow,'model':model}
                        try:
                            ledger,rejected=engine.portfolio(scores[model],prices,calendar,cost,borrow,delay,prepared=states[model])
                            attribution=ledger.attrs.pop('security_attribution')
                            if not ledger.one_way_turnover.gt(0).any():raise ValueError('No executable turnover')
                            summary=summarize(ledger)
                            if not np.isclose(attribution.net_initial_capital.sum(),summary['total_net'],atol=1e-9):raise ValueError('Attribution mismatch')
                            if model=='B2':
                                old=pd.read_csv(previous/f'{mode}_delay{delay}_cost{cost}_borrow{borrow}_PRIVATE.csv',parse_dates=['date'])
                                if not ledger.date.equals(old.date):raise ValueError('B2 replay clock changed')
                                columns=[name for name in ledger.columns if name!='date']
                                if not np.allclose(ledger[columns],old[columns],atol=1e-11,rtol=1e-10):raise ValueError('B2 prior ledger regression failure')
                            filename=f'{model}_{mode}_delay{delay}_cost{cost}_borrow{borrow}_PRIVATE.csv'
                            ledger.to_csv(output/filename,index=False)
                            key.update(status='computed-conditional-settlement',entry_orders_rejected=rejected,**summary)
                            mechanical.append({**{k:key[k] for k in ['model','mode','delay','one_way_bps','borrow_bps']},
                                'net_and_costs_reconciled':True,'contributions_reconciled':True,'no_unquoted_orders':True,'prior_B2_reproduced':model=='B2'})
                            for year,group in ledger.groupby(ledger.date.dt.year):
                                annual.append({**{k:key[k] for k in ['model','mode','delay','one_way_bps','borrow_bps']},'year':int(year),'buffer_year':bool(year>2025),'net':float((1+group.net).prod()-1)})
                            if delay==0 and cost==10 and borrow==100:
                                attribution.to_csv(output/f'{model}_{mode}_reference_attribution_PRIVATE.csv',index=False)
                                joined=ledger.merge(market,on='date',validate='one_to_one').dropna(subset=['vwretd'])
                                beta=np.linalg.lstsq(np.column_stack([np.ones(len(joined)),joined.vwretd]),joined.net,rcond=None)[0]
                                absolute=attribution.net_initial_capital.abs()
                                reference[f'{model}|{mode}']={**key,'market_beta':float(beta[1]),
                                    'top10_absolute_contribution_share':float(absolute.nlargest(10).sum()/absolute.sum()) if absolute.sum() else None}
                            ledgers[model]=ledger;statuses[model]='computed-conditional-settlement'
                        except ValueError as error:
                            if not str(error).startswith(ESTIMATION_FAILURES):raise
                            key.update(status='not-estimable',reason=str(error));statuses[model]='not-estimable'
                            if delay==0 and cost==10 and borrow==100:reference[f'{model}|{mode}']=key.copy()
                        scenarios.append(key)
                    for older,newer in PAIRS:
                        row={'mode':mode,'multiplier':multiplier,'delay':delay,'one_way_bps':cost,'borrow_bps':borrow,'older':older,'newer':newer}
                        if older in ledgers and newer in ledgers:
                            row.update(status='computed-conditional-settlement',**paired(ledgers[older],ledgers[newer],weights))
                        else:
                            row.update(status='not-estimable',reason='Both complete aligned model ledgers required',older_status=statuses[older],newer_status=statuses[newer])
                        comparisons.append(row)
            print('MODEL_COMPARISON_CHECKPOINT',mode,delay,flush=True)
        del states,prices
    results=pd.DataFrame(scenarios);pairs=pd.DataFrame(comparisons)
    assert len(results)==324 and len(pairs)==324
    results.to_csv(output/'all_324_model_scenarios_PRIVATE.csv',index=False)
    pairs.to_csv(output/'all_324_pairwise_comparisons_PRIVATE.csv',index=False)
    pd.DataFrame(annual).to_csv(output/'all_annual_results_PRIVATE.csv',index=False)
    pd.DataFrame(mechanical).to_csv(output/'mechanical_checks_PRIVATE.csv',index=False)
    (output/'reference_diagnostics_PRIVATE.json').write_text(json.dumps(reference,indent=2))
    hashes['frozen_predictions']=sha(prediction_path)
    (output/'input_fingerprints_PRIVATE.json').write_text(json.dumps(hashes,indent=2))
    (output/'manifest.json').write_text(json.dumps({'status':'frozen-three-model-strategy-comparison-processed',
        'reference_status':{key:value['status'] for key,value in reference.items()},
        'all_324_scenarios_computed':bool(results.status.eq('computed-conditional-settlement').all()),
        'all_B2_scenarios_reproduced':bool(results.loc[results.model.eq('B2'),'status'].eq('computed-conditional-settlement').all()),
        'supplemental_historical_design':True,'observed_cash_settlement_validated':False,
        'outputs':{p.name:sha(p) for p in output.iterdir() if p.is_file()}},indent=2))
    print('MODEL_STRATEGY_COMPARISON_COMPLETED',flush=True)
