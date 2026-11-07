import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('book_v3',Path(__file__).with_name('implementation_v3.py'))
v3=importlib.util.module_from_spec(spec);spec.loader.exec_module(v3)


def fixture():
    dates=pd.bdate_range('2025-01-01',periods=12)
    prices=pd.DataFrame([(date,asset,0.,10.,'N','A','NA','D1') for date in dates for asset in [1,2]],
        columns=['date','permno','total_return','close','delisting','trading_status','return_missing_flag','return_duration_flag'])
    prices['previous_price_date']=prices.groupby('permno').date.shift(1)
    prices['resolved_return']=prices.total_return;prices['return_provenance']='original-crsp'
    predictions=pd.DataFrame({'date':[dates[0]]*2,'permno':[1,2],'B2':[1.,-1.]})
    return dates,prices,predictions


def test_locked_holdings_preserve_notional_when_other_assets_pay_costs():
    drifted=np.array([.6,.2,-.8]);planned=np.array([0.,.8,-.8]);tradable=np.array([False,True,True])
    desired,cost,_=v3.rebalance(drifted,planned,tradable,.002)
    assert desired[0]*(1-cost)==pytest.approx(drifted[0])
    assert desired[:2].sum()<=.8+1e-10
    assert cost>0


def test_bridge_marks_are_explicit_and_held_units_wait_for_a_quote():
    dates,prices,predictions=fixture()
    gap=prices.permno.eq(1)&prices.date.isin(dates[3:8])
    prices.loc[gap,['total_return','resolved_return','close']]=np.nan
    prices.loc[gap,['return_missing_flag','return_duration_flag','trading_status']]=['MP','MR','H']
    recovery=prices.permno.eq(1)&prices.date.eq(dates[8])
    prices.loc[recovery,['total_return','resolved_return','close']]=[-.5,-.5,5.]
    prices.loc[recovery,'return_duration_flag']='P5'
    prices.loc[recovery,'previous_price_date']=dates[2]
    marked=v3.certified_stale_marks(prices,dates)
    marked_gap=marked.permno.eq(1)&marked.date.isin(dates[3:8])
    assert marked.loc[marked_gap,'return_provenance'].str.startswith('stale-valuation').all()
    ledger,_=v3.portfolio(predictions,marked,dates,10,100,0)
    assert ledger.unquoted_traded_notional.max()<1e-12
    assert ledger.locked_gross_exposure.iloc[6]>0  # Planned five-day exit was blocked.
    assert ledger.gross.iloc[8]<-.09
    detail=ledger.attrs['security_attribution']
    assert detail.net_initial_capital.sum()==pytest.approx((1+ledger.net).prod()-1,abs=1e-10)


def test_missing_corporate_action_or_uncertified_recovery_still_stops():
    dates,prices,predictions=fixture()
    missing=prices.permno.eq(1)&prices.date.eq(dates[3])
    prices.loc[missing,['total_return','resolved_return','close']]=np.nan
    prices.loc[missing,'return_missing_flag']='MV'
    marked=v3.certified_stale_marks(prices,dates)
    with pytest.raises(ValueError,match='Unresolved held return'):
        v3.portfolio(predictions,marked,dates,0,0,0)


def test_unavailable_entry_is_not_replaced_with_a_hindsight_winner():
    dates,prices,predictions=fixture()
    prices.loc[prices.permno.eq(1)&prices.date.eq(dates[1]),'trading_status']='H'
    ledger,rejected=v3.portfolio(predictions,prices,dates,0,0,0)
    assert rejected==1
    assert ledger.net_exposure.min()==pytest.approx(-.2)


def test_an_active_status_and_valuation_price_do_not_replace_a_missing_execution_quote():
    dates,prices,predictions=fixture()
    prices['execution_close']=prices.close
    prices.loc[prices.permno.eq(1)&prices.date.eq(dates[1]),'execution_close']=np.nan
    _,rejected=v3.portfolio(predictions,prices,dates,0,0,0)
    assert rejected==1


def test_future_payoff_does_not_change_prior_trades_or_valuation_marks():
    dates,prices,predictions=fixture()
    gap=prices.permno.eq(1)&prices.date.eq(dates[3])
    prices.loc[gap,['total_return','resolved_return','close']]=np.nan
    prices.loc[gap,['return_missing_flag','return_duration_flag','trading_status']]=['MP','MR','H']
    recovery=prices.permno.eq(1)&prices.date.eq(dates[4])
    prices.loc[recovery,'return_duration_flag']='P1'
    prices.loc[recovery,'previous_price_date']=dates[2]
    first=v3.certified_stale_marks(prices,dates)
    a,_=v3.portfolio(predictions,first,dates,10,100,0)
    prices.loc[recovery,['total_return','resolved_return']]=.2
    second=v3.certified_stale_marks(prices,dates)
    b,_=v3.portfolio(predictions,second,dates,10,100,0)
    pd.testing.assert_frame_equal(a.loc[a.date.lt(dates[4])],b.loc[b.date.lt(dates[4])])


def test_fully_quoted_book_matches_original_accounting():
    old_spec=importlib.util.spec_from_file_location('original_quote_book',Path(__file__).with_name('cloud_fit_study.py'))
    old=importlib.util.module_from_spec(old_spec);old_spec.loader.exec_module(old)
    dates,prices,predictions=fixture()
    prices.loc[prices.permno.eq(1),['total_return','resolved_return']]=.01
    prices.loc[prices.permno.eq(2),['total_return','resolved_return']]=-.005
    original,_=old.portfolio(predictions,prices,dates,10,100,0)
    replay,_=v3.portfolio(predictions,prices,dates,10,100,0)
    for column in ['net','trading_cost','one_way_turnover']:
        np.testing.assert_allclose(original[column],replay[column],atol=1e-11)


def test_valid_terminal_payoff_settles_to_cash_once():
    dates,prices,predictions=fixture()
    prices=prices.loc[~(prices.permno.eq(1)&prices.date.gt(dates[3]))].copy()
    terminal=prices.permno.eq(1)&prices.date.eq(dates[3])
    prices.loc[terminal,['total_return','resolved_return','close','delisting','trading_status']]=[-.5,-.5,np.nan,'Y','D']
    ledger,_=v3.portfolio(predictions,prices,dates,0,0,0)
    assert (1+ledger.net).prod()==pytest.approx(.9)
    assert ledger.unquoted_traded_notional.max()<1e-12


def test_reusing_immutable_market_state_does_not_change_cost_scenarios():
    dates,prices,predictions=fixture()
    state=v3.prepare(predictions,prices,dates,0)
    for cost in [0,10]:
        for borrow in [0,100]:
            expected,_=v3.portfolio(predictions,prices,dates,cost,borrow,0)
            actual,_=v3.portfolio(predictions,prices,dates,cost,borrow,0,prepared=state)
            pd.testing.assert_frame_equal(expected,actual)
    assert not state['targets'].flags.writeable
    with pytest.raises(ValueError,match='clock mismatch'):
        v3.portfolio(predictions,prices,dates,0,0,1,prepared=state)
