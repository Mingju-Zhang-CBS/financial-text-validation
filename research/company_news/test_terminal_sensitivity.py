import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import json
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('terminal',Path(__file__).with_name('cloud_terminal_sensitivity.py'))
terminal=importlib.util.module_from_spec(spec);spec.loader.exec_module(terminal)


def fixture():
    dates=pd.bdate_range('2025-01-01',periods=12)
    prices=pd.DataFrame({'permno':[1]*4,'date':dates[:4],'close':[10.,10.,10.,np.nan],
        'execution_close':[10.,10.,10.,np.nan],'delisting':['N','N','N','Y'],
        'trading_status':['A','A','A','D'],'total_return':[0.,0.,0.,np.nan],
        'resolved_return':[0.,0.,0.,np.nan],'return_provenance':['original-crsp']*4})
    events=pd.DataFrame({'permno':[1],'deldlydt':[dates[3]],'delistingdt':[dates[2]],
        'deldtprc':[10.],'delret':[np.nan],'delpaymenttype':['PRCF'],
        'delnextprc':[8.],'delnextdt':[dates[6]]})
    distributions=pd.DataFrame(columns=['permno','disexdt'])
    return dates,prices,events,distributions


def test_stale_claim_until_actual_endpoint_and_no_execution_quote():
    dates,prices,events,distributions=fixture();before=prices.copy(deep=True)
    result,audit=terminal.terminal_marks(prices,events,distributions,dates)
    assert audit.status.tolist()==['admitted-conditional-valuation']
    assert result.loc[result.date.between(dates[3],dates[5]),'resolved_return'].eq(0.).all()
    assert np.isclose(result.iloc[-1].resolved_return,-.2)
    assert result.iloc[-1].date==dates[6] and result.iloc[-1].delisting=='Y'
    assert result.loc[result.date.ge(dates[3]),'execution_close'].isna().all()
    pd.testing.assert_frame_equal(prices,before)


def test_equivocal_entitlements_and_corporate_actions_are_not_filled():
    dates,prices,events,distributions=fixture()
    events.delpaymenttype='STK'
    result,audit=terminal.terminal_marks(prices,events,distributions,dates)
    assert pd.isna(result.iloc[-1].resolved_return)
    events.delpaymenttype='PRCF'
    distributions=pd.DataFrame({'permno':[1],'disexdt':[dates[4]]})
    result,audit=terminal.terminal_marks(prices,events,distributions,dates)
    assert audit.reason.iloc[0]=='intervening-corporate-action'
    assert pd.isna(result.iloc[-1].resolved_return)


def test_anchor_conflict_duplicate_event_and_future_endpoint_rejected():
    dates,prices,events,distributions=fixture();events.deldtprc=11.
    _,audit=terminal.terminal_marks(prices,events,distributions,dates)
    assert audit.reason.iloc[0]=='unreconciled-last-trading-price'
    events.deldtprc=10.
    _,audit=terminal.terminal_marks(prices,pd.concat([events,events]),distributions,dates)
    assert audit.reason.iloc[0]=='missing-or-ambiguous-exact-daily-event'
    events.delnextdt=dates[-1]+pd.Timedelta(days=100)
    _,audit=terminal.terminal_marks(prices,events,distributions,dates)
    assert audit.reason.iloc[0]=='endpoint-outside-fixed-buffer'


def test_direct_vendor_return_has_priority_over_quote_stress():
    dates,prices,events,distributions=fixture();events.delret=-.1
    result,audit=terminal.terminal_marks(prices,events,distributions,dates,.5)
    assert np.isclose(result.iloc[-1].resolved_return,-.1)
    assert result.iloc[-1].date==dates[3]
    assert audit.reason.iloc[0]=='direct-vendor-terminal-return'


def test_quote_stress_changes_endpoint_only():
    dates,prices,events,distributions=fixture()
    low,_=terminal.terminal_marks(prices,events,distributions,dates,.5)
    high,_=terminal.terminal_marks(prices,events,distributions,dates,1.5)
    assert np.isclose(low.iloc[-1].resolved_return,-.6)
    assert np.isclose(high.iloc[-1].resolved_return,.2)
    pd.testing.assert_frame_equal(low.iloc[:-1],high.iloc[:-1])


def test_full_book_including_reference_diagnostics_with_invented_inputs(tmp_path):
    dates,prices,events,distributions=fixture()
    prices['return_missing_flag']='NA';prices['return_duration_flag']='D1'
    prices['previous_price_date']=prices.date.shift(1)
    other=pd.DataFrame({'permno':2,'date':dates,'close':10.,'execution_close':10.,'delisting':'N',
        'trading_status':'A','total_return':0.,'resolved_return':0.,'return_provenance':'original-crsp',
        'return_missing_flag':'NA','return_duration_flag':'D1','previous_price_date':pd.Series(dates).shift(1)})
    source=tmp_path/'source_reconciliation_v3_local';source.mkdir()
    path=source/'resolved_valuation_PRIVATE.parquet'
    pd.concat([prices,other],ignore_index=True).to_parquet(path,index=False)
    (source/'manifest.json').write_text(json.dumps({'outputs':{path.name:terminal.sha(path)}}))
    (tmp_path/'evaluation').mkdir()
    pd.DataFrame({'permno':[1,2],'date':[dates[0]]*2,'B2':[1.,-1.],'horizon':5,'target_type':'adjusted'}).to_parquet(tmp_path/'evaluation'/'predictions_private.parquet',index=False)
    pd.DataFrame({'date':dates,'vwretd':0.}).to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    class Database:
        def raw_sql(self,query,params):
            return events.copy() if '.stkdelists ' in query else distributions.copy()
    study=SimpleNamespace(OUT=tmp_path,ROOT=tmp_path,paired_interval=lambda values:[float(values.mean())]*2)
    terminal.execute(study,Database())
    directory=tmp_path/'terminal_sensitivity_v4'
    results=pd.read_csv(directory/'all_108_scenarios_PRIVATE.csv')
    assert len(results)==108 and results.status.eq('computed-conditional-settlement').all()
    ledger=pd.read_csv(directory/'final-quote-multiplier-1_delay0_cost10_borrow100_PRIVATE.csv')
    assert ledger.borrow.sum()>0 and ledger.unquoted_traded_notional.eq(0).all()
    assert ledger.locked_gross_exposure.gt(0).any()
    references=results.loc[results.delay.eq(0)&results.one_way_bps.eq(10)&results.borrow_bps.eq(100)]
    assert references.sort_values('mode').total_net.nunique()==3
