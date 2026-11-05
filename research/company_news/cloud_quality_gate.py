"""Outcome-blind coverage audit of prepared panels; no licensed values printed."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def check_frame(frame, links, calendar, feed):
    frame=frame.copy()
    frame['mapping_known']=False
    frame['feed_observed']=frame.date.isin(feed)
    frame['past_coverage_known']=False
    intervals={permno:group[['valid_from','valid_to']] for permno,group in links.groupby('permno')}
    day_values=calendar.to_numpy()
    feed_known=calendar.isin(feed)
    for permno,indices in frame.groupby('permno',sort=False).groups.items():
        mapped=np.zeros(len(calendar),dtype=bool)
        if permno in intervals:
            for start,end in intervals[permno].itertuples(index=False,name=None):
                mapped|=(day_values>=np.datetime64(start))&(day_values+np.timedelta64(1,'D')<=np.datetime64(end))
        complete=mapped&feed_known
        history=pd.Series(complete,index=calendar).shift(1).rolling(20,min_periods=20).sum().eq(20)
        dates=frame.loc[indices,'date']
        frame.loc[indices,'mapping_known']=pd.Series(mapped,index=calendar).reindex(dates).to_numpy()
        frame.loc[indices,'past_coverage_known']=history.reindex(dates).to_numpy()
    current=frame.mapping_known&frame.feed_observed
    frame['coverage_unknown']=~current
    frame.loc[~current&frame.news_count.eq(0),'news_count']=np.nan
    frame.loc[~current|~frame.past_coverage_known,['past_coverage','sentiment_coverage']]=np.nan
    return frame


def holding_labels(frame, prices, calendar, market):
    frame=frame.copy()
    assets=pd.Index(sorted(frame.permno.unique()))
    returns=prices.pivot(index='date',columns='permno',values='total_return').reindex(index=calendar,columns=assets)
    closes=prices.pivot(index='date',columns='permno',values='close').reindex(index=calendar,columns=assets)
    numeric_returns=returns.to_numpy(dtype=float,na_value=np.nan)
    if np.any(numeric_returns[np.isfinite(numeric_returns)]<-1):
        raise ValueError('Invalid stock total return')
    for permno, firm in prices.groupby('permno'):
        last=firm.sort_values('date').iloc[-1]
        if last.delisting=='Y' and pd.notna(last.total_return):
            returns.loc[calendar>last.date,permno]=0.
    date_indices=calendar.get_indexer(frame.date)
    if (date_indices<0).any():
        raise ValueError('Signal outside holding calendar')
    asset_indices=assets.get_indexer(frame.permno)
    entry=(date_indices+1)<len(calendar)
    frame['entry_date']=pd.NaT
    frame.loc[entry,'entry_date']=calendar[date_indices[entry]+1]
    close_values=closes.to_numpy(dtype=float,na_value=np.nan)
    entry[entry]&=np.isfinite(close_values[date_indices[entry]+1,asset_indices[entry]])&(close_values[date_indices[entry]+1,asset_indices[entry]]>0)
    values=returns.to_numpy(dtype=float,na_value=np.nan)
    market_values=market.reindex(calendar).to_numpy(dtype=float,na_value=np.nan)
    for horizon in [1,5,20]:
        end_known=(date_indices+horizon+1)<len(calendar)
        frame[f'end_{horizon}']=pd.NaT
        frame.loc[end_known,f'end_{horizon}']=calendar[date_indices[end_known]+horizon+1]
        valid=entry&((date_indices+horizon+1)<len(calendar))
        rows=date_indices[valid,None]+np.arange(2,horizon+2)[None,:]
        raw=np.prod(1+values[rows,asset_indices[valid,None]],axis=1)-1
        benchmark=np.prod(1+market_values[rows],axis=1)-1
        frame[f'raw_{horizon}']=np.nan
        frame[f'market_{horizon}']=np.nan
        frame.loc[valid,f'raw_{horizon}']=raw
        frame.loc[valid,f'market_{horizon}']=benchmark
        frame[f'adjusted_{horizon}']=frame[f'raw_{horizon}']-frame[f'market_{horizon}']
    return frame


def execute(study, links, new_market, db):
    root=study.OUT
    calendar=pd.DatetimeIndex(new_market.date).sort_values().unique()
    cutoff=(calendar.tz_localize('America/New_York')+pd.Timedelta(hours=23,minutes=59,seconds=59)).tz_convert('UTC')
    feed=set()
    for year in range(2009,2027):
        timestamps=pd.read_parquet(root/f'news_events_{year}.parquet',columns=['timestamp_utc'])
        positions=cutoff.searchsorted(pd.to_datetime(timestamps.timestamp_utc,utc=True))
        feed.update(calendar[positions[positions<len(calendar)]])
    summaries=[]
    for year in range(2010,2026):
        frame=pd.read_parquet(root/f'panel_{year}.parquet')
        checked=check_frame(frame,links,calendar,feed)
        holding_path=root/f'holding_prices_{year}.parquet'
        if not holding_path.exists():
            identifiers=[int(value) for value in frame.permno.unique()]
            query="SELECT permno,dlycaldt AS date,dlyret::float8 AS total_return,dlyprc::float8 AS close,dlydelflg AS delisting FROM crsp_q_stock.dsf_v2 WHERE permno=ANY(%s) AND dlycaldt BETWEEN %s AND %s ORDER BY permno,dlycaldt"
            prices=db.raw_sql(query,params=(identifiers,f'{year}-01-01',f'{year+1}-02-28'),date_cols=['date'])
            prices.to_parquet(holding_path,index=False)
        else:
            prices=pd.read_parquet(holding_path)
        holding_calendar=calendar[(calendar>=pd.Timestamp(year,1,1))&(calendar<=pd.Timestamp(year+1,2,28))]
        checked=holding_labels(checked,prices,holding_calendar,new_market.set_index('date').vwretd.astype(float))
        checked.to_parquet(root/f'panel_checked_{year}.parquet',index=False)
        summaries.append({'year':year,'eligible_company_days':len(checked),'mapping_unknown':int((~checked.mapping_known).sum()),'feed_activity_unknown':int((~checked.feed_observed).sum()),'baseline_complete':int(checked[study.BASE].notna().all(axis=1).sum()),'five_day_target_missing':int(checked.adjusted_5.isna().sum())})
        print('COVERAGE_QUALITY_YEAR_DONE',year,flush=True)
    (root/'coverage_quality_private.json').write_text(json.dumps(summaries,indent=2))
    (root/'quality_gate.json').write_text(json.dumps({'status':'coverage-reconciled; eligible baseline rows explicitly filtered','code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'outcome_blind':True,'note':'Activity of the filtered feed is not full source-completeness certification; historical scoring vintages remain unverified.'},indent=2))
    print('COVERAGE_QUALITY_GATE_FINISHED',flush=True)
