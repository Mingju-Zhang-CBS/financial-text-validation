import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('cloud_data',Path(__file__).with_name('cloud_real_study.py'))
study=importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def test_fast_compounding_keeps_total_loss_and_missing_values():
    values=pd.Series([.1,-1.,.2,np.nan,.3,.4])
    actual=study.compound(values,2)
    expected=(1+values).rolling(2).apply(np.prod,raw=True)-1
    pd.testing.assert_series_equal(actual,expected)


def test_cross_utc_year_daily_merge_uses_article_weights():
    common={'permno':1,'date':pd.Timestamp('2025-12-31'),'event_type':'earnings'}
    first=pd.DataFrame([{**common,'news_count':1,'sentiment':1.,'sentiment_observed':1,'novelty':1.,'novelty_observed':1,'novelty_missing':0.,'event_topic_counts':'{"earnings":1}'}])
    second=pd.DataFrame([{**common,'news_count':3,'sentiment':-1.,'sentiment_observed':3,'novelty':0.,'novelty_observed':3,'novelty_missing':0.,'event_topic_counts':'{"other":3}'}])
    actual=study.combine_daily([first,second]).iloc[0]
    assert actual.news_count==4
    assert actual.sentiment==-.5
    assert actual.novelty==.25
    assert actual.event_type=='other'


def test_company_universe_and_delayed_labels(tmp_path,monkeypatch):
    monkeypatch.setattr(study,'OUT',tmp_path)
    calendar=pd.bdate_range('2009-11-02','2011-02-28')
    frames=[]
    for permno,permco,cap in [(1,10,5e6),(2,10,1e6),(3,30,3e6)]:
        frame=pd.DataFrame({'permno':permno,'permco':permco,'date':calendar,'close':10.,'total_return':.01,'market_cap':cap,'dollar_volume':2e6,'delisting':'N'})
        frames.append(frame)
    prices=pd.concat(frames,ignore_index=True)
    for year in [2009,2010,2011]:
        prices.loc[prices.date.dt.year.eq(year)].to_parquet(tmp_path/f'prices_{year}.parquet',index=False)
        news=pd.DataFrame([{'permno':1,'date':pd.Timestamp(year,12,15),'news_count':1,'sentiment':.1,'sentiment_observed':1,'novelty':.5,'novelty_observed':1,'novelty_missing':0.,'event_type':'earnings','event_topic_counts':'{"earnings":1}'}])
        news.to_parquet(tmp_path/f'news_daily_{year}.parquet',index=False)
    result=study.prepare_year(2010,None,None,calendar,pd.Series(.001,index=calendar))
    assert set(result.permno)=={1,3}
    assert result.groupby(['permco','date']).size().max()==1
    assert result.raw_5.dropna().iloc[0]==pytest.approx(1.01**5-1)
    assert result.market_5.dropna().iloc[0]==pytest.approx(1.001**5-1)
    changed=prices.copy()
    changed.loc[changed.date.ge('2010-07-01')&changed.permno.eq(1),'permco']=99
    for year in [2009,2010,2011]:
        changed.loc[changed.date.dt.year.eq(year)].to_parquet(tmp_path/f'prices_{year}.parquet',index=False)
    after=study.prepare_year(2010,None,None,calendar,pd.Series(.001,index=calendar))
    pd.testing.assert_frame_equal(result.loc[result.date.lt('2010-07-01')],after.loc[after.date.lt('2010-07-01')])
