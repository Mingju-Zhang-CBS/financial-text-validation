import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('diagnostics',Path(__file__).with_name('cloud_diagnostics.py'))
diagnostics=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def test_unbalanced_within_recovers_slope_with_firm_and_date_effects():
    rng=np.random.default_rng(4)
    firm=np.repeat(np.arange(7),11);date=np.tile(np.arange(11),7)
    keep=rng.random(len(firm))>.2
    firm,date=firm[keep],date[keep]
    x=rng.normal(size=len(firm))
    y=2.5*x+np.sin(firm)+date*.2
    result=diagnostics.within(np.column_stack([y,x]),firm,date)
    slope=np.linalg.lstsq(result[:,1:],result[:,0],rcond=None)[0][0]
    assert np.isclose(slope,2.5,atol=1e-9)
    for codes in [firm,date]:
        for group in np.unique(codes):
            assert np.max(np.abs(result[codes==group].mean(axis=0)))<1e-9


def test_event_paths_separate_event_day_and_keep_empty_groups(tmp_path):
    calendar=pd.bdate_range('2020-12-01',periods=70)
    development=pd.DataFrame({'date':calendar[:10],'permno':1,'news_count':1,'novelty':np.linspace(0,1,10),'past_coverage':np.linspace(0,1,10),'sentiment':1.})
    event=pd.DataFrame({'date':[calendar[30]],'permno':[1],'news_count':[1],'novelty':[1.],'past_coverage':[.5],'sentiment':[1.]})
    panel=pd.concat([development,event],ignore_index=True)
    prices=pd.DataFrame({'date':calendar,'permno':1,'total_return':0.,'close':10.,'delisting':'N'})
    prices.loc[prices.date.eq(calendar[30]),'total_return']=.1
    prices.loc[prices.date.eq(calendar[31]),'total_return']=.02
    market=pd.DataFrame({'date':calendar,'vwretd':0.})
    result,_=diagnostics.event_paths(panel,prices,market,tmp_path)
    subset=result.loc[result.novelty_group.eq('high')&result.attention_group.eq('middle')&result.sentiment_group.eq('positive')]
    assert len(result)==27*21
    assert np.isclose(subset.loc[subset.offset.eq(0),'mean_market_adjusted_path'].iloc[0],.1)
    assert np.isclose(subset.loc[subset.offset.eq(1),'mean_market_adjusted_path'].iloc[0],.122)
    assert result.loc[result.sentiment_group.eq('neutral'),'events'].sum()==0
