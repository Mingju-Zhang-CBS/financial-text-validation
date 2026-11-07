import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('reconciliation',Path(__file__).with_name('return_reconciliation.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def test_total_return_index_adjusts_split_and_dividend_without_bridging_absent_day():
    calendar=pd.bdate_range('2025-01-01',periods=5)
    data=pd.DataFrame({'gvkey':'a','iid':'01','date':calendar[[0,1,2,4]],
        'prccd':[100.,50.,49.,48.],'ajexdi':[2.,1.,1.,1.],
        'trfd':[1.,1.,50/49,50/49],'curcdd':'USD'})
    result=r.compustat_total_returns(data,calendar)
    assert result.candidate_return.iloc[1]==pytest.approx(0.)
    assert result.candidate_return.iloc[2]==pytest.approx(0.)
    assert pd.isna(result.candidate_return.iloc[3])


def test_identity_currency_and_factor_failures_do_not_create_returns():
    calendar=pd.bdate_range('2025-01-01',periods=4)
    data=pd.DataFrame({'gvkey':['a']*4,'iid':['01','01','02','02'],'date':calendar,
        'prccd':[10.]*4,'ajexdi':[1.,1.,1.,np.nan],'trfd':[1.]*4,'curcdd':['USD','CAD','USD','USD']})
    assert r.compustat_total_returns(data,calendar).candidate_return.isna().all()


def test_alternate_requires_daily_overlap_and_does_not_fill_corporate_action():
    dates=pd.bdate_range('2025-01-01',periods=28)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':[.01]*20+[np.nan,.01]*4,
        'return_missing_flag':['NA']*20+['MP','NA','MV','NA','DM','NA','GP','NA'],
        'return_duration_flag':['D1']*20+['MR','D1']*4,'delisting':'N'})
    alternative=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01})
    result,_=r.accept_daily_candidates(primary,alternative)
    assert result.resolved_return.iloc[20]==pytest.approx(.01)
    assert result.resolved_return.iloc[[22,24,26]].isna().all()
    alternative.loc[0,'candidate_return']=.2
    failed,_=r.accept_daily_candidates(primary,alternative)
    assert failed.resolved_return.iloc[[20,22,24,26]].isna().all()


def test_short_or_multi_session_overlap_is_not_daily_validation():
    dates=pd.bdate_range('2025-01-01',periods=23)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':[.01]*22+[np.nan],
        'return_missing_flag':['NA']*22+['MP'],'return_duration_flag':['P1']*22+['MR'],'delisting':'N'})
    candidate=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01})
    result,_=r.accept_daily_candidates(primary,candidate)
    assert pd.isna(result.resolved_return.iloc[-1])


def test_effective_security_links_quarantine_ambiguous_share_classes():
    dates=pd.bdate_range('2025-01-01',periods=2)
    keys=pd.DataFrame({'permno':[1,1],'date':dates})
    links=pd.DataFrame({'permno':[1,1],'valid_from':[dates[0]]*2,'valid_to':[dates[1],dates[0]],'gvkey':['a','b'],'iid':['01','02']})
    result=r.exact_historical_links(keys,links)
    assert result.date.tolist()==[dates[1]]


def test_bridge_requires_matching_previous_price_date_and_trading_duration():
    dates=pd.bdate_range('2025-01-01',periods=7)
    assert r.validate_bridge(dates,dates[0],dates[3],dates[0],'P2')
    assert not r.validate_bridge(dates,dates[0],dates[3],dates[1],'P2')
    assert not r.validate_bridge(dates,dates[0],dates[3],dates[0],'D3')


def test_one_alternate_security_cannot_supply_two_simultaneous_permnos():
    date=pd.Timestamp('2025-01-02')
    keys=pd.DataFrame({'permno':[1,2],'date':date})
    links=pd.DataFrame({'permno':[1,2],'valid_from':date,'valid_to':date,'gvkey':'a','iid':'01'})
    assert r.exact_historical_links(keys,links).empty


def test_alternate_daily_fill_does_not_double_count_multi_session_recovery():
    dates=pd.bdate_range('2025-01-01',periods=24)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':[.01]*20+[np.nan,.0201,.01,.01],
        'return_missing_flag':['NA']*20+['MP','NA','NA','NA'],
        'return_duration_flag':['D1']*20+['MR','P1','D1','D1'],'delisting':'N',
        'previous_price_date':pd.Series(dates).shift(1)})
    primary.loc[21,'previous_price_date']=dates[19]
    alternative=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01})
    result,_=r.accept_daily_candidates(primary,alternative,calendar=dates)
    assert (1+result.resolved_return.iloc[20:22]).prod()-1==pytest.approx(.0201)
    assert result.return_provenance.iloc[21]=='validated-daily-decomposition-of-crsp-bridge'
    primary.loc[21,'previous_price_date']=dates[18]
    failed,_=r.accept_daily_candidates(primary,alternative,calendar=dates)
    assert pd.isna(failed.resolved_return.iloc[20])
    assert failed.resolved_return.iloc[21]==pytest.approx(.0201)


def test_local_overlap_is_fixed_and_past_only_not_best_window_selection():
    dates=pd.bdate_range('2025-01-01',periods=100)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':.01,'return_missing_flag':'NA','return_duration_flag':'D1','delisting':'N'})
    primary.loc[80,['total_return','return_missing_flag','return_duration_flag']]=[np.nan,'MP','MR']
    candidate=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01})
    candidate.loc[[0,99],'candidate_return']=.2
    rejected,_=r.accept_daily_candidates(primary,candidate)
    assert pd.isna(rejected.resolved_return.iloc[80])
    local,_=r.accept_daily_candidates(primary,candidate,overlap_scope='local-prior20')
    assert local.resolved_return.iloc[80]==.01
    candidate.loc[75,'candidate_return']=.2
    failed,_=r.accept_daily_candidates(primary,candidate,overlap_scope='local-prior20')
    assert pd.isna(failed.resolved_return.iloc[80])
