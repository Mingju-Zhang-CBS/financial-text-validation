"""Invented inputs exercise ranking isolation, paired inference and replay parity."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import numpy as np
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('comparison',Path(__file__).with_name('cloud_model_strategy_comparison.py'))
comparison=importlib.util.module_from_spec(spec);spec.loader.exec_module(comparison)
engine=comparison.load('comparison_test_engine','implementation_v3.py')


def fixture():
    dates=pd.bdate_range('2025-01-01',periods=12)
    prices=pd.DataFrame([(date,asset,.005 if asset==1 else -.005,10.,'N','A','NA','D1') for date in dates for asset in [1,2]],
        columns=['date','permno','total_return','close','delisting','trading_status','return_missing_flag','return_duration_flag'])
    prices['execution_close']=prices.close;prices['resolved_return']=prices.total_return
    prices['return_provenance']='original-crsp';prices['previous_price_date']=prices.groupby('permno').date.shift(1)
    predictions=pd.DataFrame({'date':[dates[0]]*2,'permno':[1,2],'B0':[-1.,1.],'B1':[-1.,1.],'B2':[1.,-1.],
        'target':[np.nan,np.nan],'horizon':5,'target_type':'adjusted'})
    return dates,prices,predictions


def stamp(folder):
    (folder/'manifest.json').write_text(json.dumps({'outputs':{p.name:comparison.sha(p) for p in folder.iterdir() if p.is_file() and p.name!='manifest.json'}}))


def test_ranking_changes_holdings_without_changing_forecast_universe_or_targets():
    dates,prices,predictions=fixture();original=predictions.copy(deep=True)
    b0=comparison.ranking_input(predictions,'B0');b2=comparison.ranking_input(predictions,'B2')
    assert b0[['date','permno']].equals(b2[['date','permno']])
    assert len(b0)==len(predictions)  # Missing ex-post targets are not filters.
    first,_=engine.portfolio(b0,prices,dates,0,0,0)
    second,_=engine.portfolio(b2,prices,dates,0,0,0)
    assert (1+first.net).prod()<1<(1+second.net).prod()
    pd.testing.assert_frame_equal(predictions,original)
    predictions.loc[0,'B1']=np.nan
    with pytest.raises(ValueError,match='share every company-day'):comparison.ranking_input(predictions,'B2')


def test_paired_blocks_match_original_procedure_and_do_not_drop_bad_dates():
    study=comparison.load('comparison_original_interval','cloud_real_study.py')
    values=np.random.default_rng(17).normal(0,.01,37)
    weights=comparison.bootstrap_weights(len(values))
    np.testing.assert_allclose(np.quantile(weights@values,[.025,.975]),study.paired_interval(values),atol=1e-15)
    dates=pd.bdate_range('2025-01-01',periods=37)
    ledger=pd.DataFrame({'date':dates,'net':values,'one_way_turnover':1.,'borrow':0.,'trading_cost':0.})
    zero=comparison.paired(ledger,ledger,weights)
    assert zero['daily_mean_net_increment']==zero['lower95']==zero['upper95']==0
    with pytest.raises(ValueError,match='Unaligned'):comparison.paired(ledger,ledger.iloc[:-1],weights)


def test_buffer_payout_is_in_cumulative_spread_but_not_confirmation_daily_test():
    dates=pd.to_datetime(['2025-12-30','2025-12-31','2026-01-02'])
    older=pd.DataFrame({'date':dates,'net':[0.,0.,0.],'one_way_turnover':0.,'borrow':0.,'trading_cost':0.})
    newer=older.copy();newer.loc[2,'net']=.1
    result=comparison.paired(older,newer,comparison.bootstrap_weights(2))
    assert result['daily_mean_net_increment']==0
    assert result['complete_ledger_cumulative_increment']==pytest.approx(.1)


def test_new_model_missing_holding_value_stops_instead_of_deleting_that_security():
    dates=pd.bdate_range('2025-01-01',periods=12)
    prices=pd.DataFrame([(d,a,0.,10.,'N','A') for d in dates for a in [1,2,3,4]],columns=['date','permno','resolved_return','execution_close','delisting','trading_status'])
    predictions=pd.DataFrame({'date':[dates[0]]*4,'permno':[1,2,3,4],'B0':[3,2,1,0],'B1':[3,2,1,0],'B2':[1,3,2,0]})
    prices.loc[prices.permno.eq(1)&prices.date.eq(dates[3]),'resolved_return']=np.nan
    with pytest.raises(ValueError,match='Unresolved held return'):engine.portfolio(comparison.ranking_input(predictions,'B0'),prices,dates,10,100,0)
    engine.portfolio(comparison.ranking_input(predictions,'B2'),prices,dates,10,100,0)


def test_full_comparison_reproduces_B2_and_keeps_all_324_model_and_pair_rows(tmp_path):
    dates,prices,predictions=fixture()
    evaluation=tmp_path/'evaluation';evaluation.mkdir();predictions.to_parquet(evaluation/'predictions_private.parquet',index=False)
    (evaluation/'paired_contrasts_private.json').write_text(json.dumps([{'horizon':5,'target':'adjusted','date_equal_weight_mse_improvement':0.,'interval_95':[0.,0.]}]));stamp(evaluation)
    previous=tmp_path/'terminal_sensitivity_v4_checked';previous.mkdir()
    (previous/'protocol.json').write_text(json.dumps({'prediction_sha256':comparison.sha(evaluation/'predictions_private.parquet')}))
    b2=comparison.ranking_input(predictions,'B2')
    for multiplier in [.5,1.,1.5]:
        mode=f'final-quote-multiplier-{multiplier:g}'
        prices.to_parquet(previous/(mode+'_valuation_PRIVATE.parquet'),index=False)
        for delay in [0,1,2]:
            state=engine.prepare(b2,prices,dates,delay)
            for cost in [0,5,10,20]:
                for borrow in [0,100,300]:
                    ledger,_=engine.portfolio(b2,prices,dates,cost,borrow,delay,prepared=state)
                    ledger.attrs={};ledger.to_csv(previous/f'{mode}_delay{delay}_cost{cost}_borrow{borrow}_PRIVATE.csv',index=False)
    stamp(previous)
    pd.DataFrame({'date':dates,'vwretd':0.}).to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    comparison.execute(SimpleNamespace(OUT=tmp_path,ROOT=tmp_path))
    output=tmp_path/'model_strategy_comparison_20261108'
    results=pd.read_csv(output/'all_324_model_scenarios_PRIVATE.csv')
    pairs=pd.read_csv(output/'all_324_pairwise_comparisons_PRIVATE.csv')
    assert len(results)==len(pairs)==324
    assert results.status.eq('computed-conditional-settlement').all()
    assert pairs.status.eq('computed-conditional-settlement').all()
    equal=pairs.loc[pairs.older.eq('B0')&pairs.newer.eq('B1')]
    assert equal.daily_mean_net_increment.eq(0).all()
    assert pairs.loc[pairs.older.eq('B0')&pairs.newer.eq('B2'),'complete_ledger_cumulative_increment'].gt(0).all()
    manifest=json.loads((output/'manifest.json').read_text());assert manifest['all_B2_scenarios_reproduced']
    assert comparison.verify(output)
    reporting=comparison.load('comparison_test_reporting','cloud_model_strategy_report.py')
    reporting.execute(SimpleNamespace(OUT=tmp_path,ROOT=tmp_path))
    report=tmp_path/'model_strategy_report_20261108'
    assert comparison.verify(report)
    aggregate=json.loads((report/'aggregate_research_summary.json').read_text())
    assert len(aggregate['reference_models'])==len(aggregate['reference_pairwise'])==9
    assert not {'permno','date','prediction','gvkey'}&set(aggregate)
    assert len(pd.read_csv(report/'aggregate_model_scenarios.csv'))==324


def test_relative_gain_does_not_get_reported_as_absolute_profit():
    reporting=comparison.load('comparison_test_verdict','cloud_model_strategy_report.py')
    judgment=reporting.verdict({'status':'computed-conditional-settlement','lower95':.001,'upper95':.002},-.3)
    assert 'positive historical' in judgment and 'loss reduction' in judgment
    assert 'not established' in reporting.verdict({'status':'computed-conditional-settlement','lower95':-.001,'upper95':.002})
