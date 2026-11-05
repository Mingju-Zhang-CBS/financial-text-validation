import importlib.util
from pathlib import Path

import pandas as pd

spec=importlib.util.spec_from_file_location('coverage_gate',Path(__file__).with_name('cloud_quality_gate.py'))
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_unmapped_stock_is_not_known_no_news():
    calendar=pd.bdate_range('2025-01-01',periods=40)
    frame=pd.DataFrame({'permno':[1,2],'date':[calendar[30]]*2,'news_count':[0,0],'past_coverage':[0.,0.],'sentiment_coverage':[0.,0.]})
    links=pd.DataFrame({'permno':[1],'valid_from':[pd.Timestamp('2020-01-01')],'valid_to':[pd.Timestamp('2030-01-01')]})
    result=gate.check_frame(frame,links,calendar,set(calendar))
    assert result.news_count.iloc[0]==0
    assert pd.isna(result.news_count.iloc[1])
    assert result.past_coverage.iloc[0]==0
    assert pd.isna(result.past_coverage.iloc[1])


def test_feed_gap_invalidates_later_coverage_window():
    calendar=pd.bdate_range('2025-01-01',periods=40)
    frame=pd.DataFrame({'permno':[1],'date':[calendar[30]],'news_count':[0],'past_coverage':[0.],'sentiment_coverage':[0.]})
    links=pd.DataFrame({'permno':[1],'valid_from':[pd.Timestamp('2020-01-01')],'valid_to':[pd.Timestamp('2030-01-01')]})
    result=gate.check_frame(frame,links,calendar,set(calendar)-{calendar[20]})
    assert result.news_count.iloc[0]==0
    assert pd.isna(result.past_coverage.iloc[0])


def test_terminal_return_then_cash_in_holding_label():
    calendar=pd.bdate_range('2025-01-01',periods=25)
    frame=pd.DataFrame({'date':[calendar[0]],'permno':[1]})
    prices=pd.DataFrame({'date':calendar[:3],'permno':[1]*3,'total_return':[0.,0.,-.5],'close':[10.,10.,float('nan')],'delisting':['N','N','Y']})
    result=gate.holding_labels(frame,prices,calendar,pd.Series(0.,index=calendar))
    assert result.raw_5.iloc[0]==-.5
    assert result.raw_20.iloc[0]==-.5


def test_nullable_database_floats_preserve_missing_labels():
    calendar=pd.bdate_range('2025-01-01',periods=25)
    frame=pd.DataFrame({'date':[calendar[0]],'permno':[1]})
    prices=pd.DataFrame({'date':calendar,'permno':[1]*25,
        'total_return':pd.Series([0.,0.,pd.NA]+[0.]*22,dtype='Float64'),
        'close':pd.Series([10.]*25,dtype='Float64'),'delisting':['N']*25})
    market=pd.Series([0.]*25,index=calendar,dtype='Float64')
    result=gate.holding_labels(frame,prices,calendar,market)
    assert pd.isna(result.raw_1.iloc[0])
    assert pd.isna(result.raw_5.iloc[0])
    assert result.end_5.iloc[0]==calendar[6]
