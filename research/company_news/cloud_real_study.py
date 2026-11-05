"""Private archive study. Run on authenticated WRDS Cloud; no redistribution grant."""
from pathlib import Path
import datetime
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import sys
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits


ROOT = Path.home() / 'company_news_research_20261105'
OUT = ROOT / 'private_archive_v2'
BASE = ['return_1','return_5','return_20','volatility_20','log_cap','log_liquidity','past_coverage']
SENTIMENT = ['sentiment','has_news','sentiment_missing']
NOVELTY = ['novelty','novelty_missing','sentiment_novelty','sentiment_coverage']


def save_json(name, value):
    (OUT/name).write_text(json.dumps(value,default=str,indent=2))


def frame_cache(db, name, query, dates):
    path = OUT/name
    existing=ROOT/'real_data_cache'/name
    if not path.exists() and existing.exists():
        path.symlink_to(existing)
    if path.exists():
        return pd.read_parquet(path)
    frame = db.raw_sql(query,date_cols=dates)
    frame.to_parquet(path,index=False)
    (OUT/(name+'.sql')).write_text(query)
    return frame


def model(name, alpha):
    numeric = BASE + (SENTIMENT if name!='B0' else []) + (NOVELTY if name=='B2' else [])
    blocks = [('numeric',Pipeline([('missing',SimpleImputer(strategy='median')),('scale',StandardScaler())]),numeric)]
    if name=='B2':
        blocks.append(('topic',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['event_type']))
    return Pipeline([('transform',ColumnTransformer(blocks)),('ridge',Ridge(alpha=alpha))])


def paired_interval(dates, seed=20261105):
    values=np.asarray(dates,dtype=float)
    generator=np.random.default_rng(seed)
    length=min(20,len(values))
    samples=[]
    for _ in range(2000):
        starts=generator.integers(0,len(values)-length+1,size=int(np.ceil(len(values)/length)))
        indices=np.concatenate([np.arange(start,start+length) for start in starts])[:len(values)]
        samples.append(values[indices].mean())
    return np.quantile(samples,[.025,.975]).tolist()


def combine_daily(parts):
    daily=pd.concat(parts,ignore_index=True)
    if not daily.duplicated(['permno','date']).any():
        return daily
    daily['sentiment_sum']=daily.sentiment.fillna(0)*daily.sentiment_observed
    daily['novelty_sum']=daily.novelty.fillna(0)*daily.novelty_observed
    def topic_mode(values):
        counts=Counter()
        for value in values:
            counts.update(json.loads(value))
        return sorted(counts,key=lambda topic:(-counts[topic],topic))[0]
    combined=daily.groupby(['permno','date'],as_index=False).agg(news_count=('news_count','sum'),sentiment_sum=('sentiment_sum','sum'),sentiment_observed=('sentiment_observed','sum'),novelty_sum=('novelty_sum','sum'),novelty_observed=('novelty_observed','sum'),event_type=('event_topic_counts',topic_mode))
    combined['sentiment']=combined.sentiment_sum/combined.sentiment_observed.replace(0,np.nan)
    combined['novelty']=combined.novelty_sum/combined.novelty_observed.replace(0,np.nan)
    combined['novelty_missing']=1-combined.novelty_observed/combined.news_count
    return combined


def compound(values, window):
    factors=1+values
    if factors.dropna().lt(0).any():
        raise ValueError('Stock return below minus one')
    logs=np.log(factors.where(factors.gt(0),1))
    product=np.exp(logs.rolling(window,min_periods=window).sum())
    product=product.mask(factors.eq(0).rolling(window,min_periods=window).sum().gt(0),0)
    return product.where(factors.notna().rolling(window,min_periods=window).sum().eq(window))-1


def prepare_year(year, adapter, links, calendar, market):
    frames=[pd.read_parquet(OUT/f'prices_{part}.parquet') for part in [year-1,year,year+1]]
    raw=pd.concat(frames,ignore_index=True).sort_values(['permno','date'])
    if not raw.date.isin(calendar).all():
        raise ValueError('CIZ rows outside the audited exchange calendar')
    if raw.duplicated(['permno','date']).any():
        raise ValueError('Duplicate CIZ security-session')
    expanded=[]
    for permno, firm in raw.groupby('permno',sort=False):
        end=calendar.get_indexer([firm.date.iloc[-1]])[0]
        if firm.delisting.iloc[-1]=='Y' and pd.notna(firm.total_return.iloc[-1]):
            end=min(end+22,len(calendar)-1)
        index=calendar[(calendar>=firm.date.iloc[0])&(calendar<=calendar[end])]
        aligned=firm.set_index('date').reindex(index)
        aligned.index.name='date'
        aligned['original_row']=aligned.permno.notna()
        terminal=aligned.index>firm.date.iloc[-1]
        if terminal.any():
            aligned.loc[terminal,'total_return']=0.0
            aligned.loc[terminal,['close','market_cap','dollar_volume']]=0.0
        aligned['permno']=permno
        aligned['permco']=aligned.permco.ffill()
        expanded.append(aligned.reset_index())
    frame=pd.concat(expanded,ignore_index=True).sort_values(['permno','date']).reset_index(drop=True)
    all_news=[]
    for part in [year-1,year,year+1]:
        if part<2009:
            continue
        path=OUT/f'news_daily_{part}.parquet'
        if path.exists():
            all_news.append(pd.read_parquet(path))
    daily=combine_daily(all_news)
    frame=frame.merge(daily,on=['permno','date'],how='left',validate='one_to_one')
    frame['news_count']=frame.news_count.fillna(0)
    frame['has_news']=frame.news_count.gt(0).astype(int)
    frame['sentiment_missing']=(frame.has_news.eq(1)&frame.sentiment.isna()).astype(int)
    frame['sentiment']=frame.sentiment.fillna(0)
    frame['novelty']=frame.novelty.fillna(0)
    frame['novelty_missing']=frame.novelty_missing.fillna(0)
    frame['event_type']=frame.event_type.fillna('no-news')
    frame=frame.sort_values(['permno','date']).reset_index(drop=True)
    grouped=frame.groupby('permno',sort=False)
    frame['return_1']=frame.total_return
    for window in [5,20]:
        frame[f'return_{window}']=grouped.total_return.transform(lambda values:compound(values,window))
    frame['volatility_20']=grouped.total_return.transform(lambda values:values.rolling(20).std())
    frame['past_coverage']=grouped.news_count.transform(lambda values:values.shift(1).rolling(20,min_periods=20).mean())
    frame['liquidity_20']=grouped.dollar_volume.transform(lambda values:values.rolling(20,min_periods=20).mean())
    frame['log_cap']=np.log(frame.market_cap.where(frame.market_cap>0))
    frame['log_liquidity']=np.log(frame.dollar_volume.where(frame.dollar_volume>0))
    frame['sentiment_novelty']=frame.sentiment*frame.novelty
    frame['sentiment_coverage']=frame.sentiment*np.log1p(frame.past_coverage)
    frame['month']=frame.date.dt.to_period('M')
    month_ends=pd.Series(calendar,index=calendar.to_period('M')).groupby(level=0).max()
    snapshots=frame.loc[frame.date.eq(frame.month.map(month_ends))&frame.original_row].copy()
    capital=snapshots.groupby(['month','permco']).market_cap.sum().rename('company_cap')
    snapshots=snapshots.join(capital,on=['month','permco'])
    snapshots=snapshots.sort_values(['market_cap','permno'],ascending=[False,True]).drop_duplicates(['month','permco'])
    snapshots=snapshots.loc[snapshots.close.ge(5)&snapshots.liquidity_20.ge(1e6)]
    snapshots=snapshots.sort_values(['month','company_cap','permco'],ascending=[True,False,True]).groupby('month').head(1000)
    snapshots['month']=snapshots.month+1
    eligible=snapshots[['month','permno']].assign(eligible=True)
    frame=frame.merge(eligible,on=['month','permno'],how='left',validate='many_to_one').sort_values(['permno','date']).reset_index(drop=True)
    frame['eligible']=frame.eligible.eq(True)&frame.original_row&frame.close.gt(0)
    frame['market_return']=frame.date.map(market)
    grouped=frame.groupby('permno',sort=False)
    frame['entry_date']=grouped.date.shift(-1)
    entry_valid=grouped.original_row.shift(-1).eq(True)&grouped.close.shift(-1).gt(0)
    for horizon in [1,5,20]:
        frame[f'end_{horizon}']=grouped.date.shift(-(horizon+1))
        for source,target in [('total_return','raw'),('market_return','market')]:
            frame[f'{target}_{horizon}']=grouped[source].transform(lambda values:compound(values.shift(-2),horizon).shift(-(horizon-1)))
            frame.loc[~entry_valid,f'{target}_{horizon}']=np.nan
        frame[f'adjusted_{horizon}']=frame[f'raw_{horizon}']-frame[f'market_{horizon}']
    result=frame.loc[frame.date.dt.year.eq(year)&frame.eligible].copy()
    result.to_parquet(OUT/f'panel_{year}.parquet',index=False)
    print('PANEL_PREPARED',year,len(result),flush=True)
    return result


def execute(db, adapter, links, new_market):
    OUT.mkdir(exist_ok=False)
    freeze={'id':'company-news-private-archive-v2','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'outcomes_inspected_before_freeze':'schema,coverage,mapping and bounded score diagnostics only; no forecast performance',
        'period':[2010,2025],'train':[2010,2017],'validation':[2018,2020],'confirmation':[2021,2025],
        'amendments':['CIZ quarterly source preserves 2025 and forward buffer','vendor receipt is an availability proxy; no separate publication/scoring clock claimed','historical scoring vintages unverified; retrospective archive study','event sentiment instead of market-trained CSS/NIP','log1p similarity days / log(366); missing novelty fraction explicit','one largest share class per prior-month company; rank summed common-share capitalization'],
        'universe':{'companies':1000,'price':5,'prior_20_session_dollar_volume':1e6,'relevance':100},
        'primary':'date-equal-weight paired five-session market-adjusted MSE B0 minus B2',
        'horizons':[1,5,20],'alphas':[.1,1.,10.],'cost_bps':[0,5,10,20],'borrow_bps':[0,100,300],'extra_delays':[0,1,2],
        'rights':'academic private computation only; raw/row-level/models/real aggregates not cleared for GitHub',
        'implementation':'next-session close entry; terminal valid delisting return then cash; missing held returns stop ledger',
        'runtime':{'python':sys.version,'packages':{name:importlib.metadata.version(name) for name in ['pandas','numpy','scikit-learn','scipy']}}}
    save_json('protocol_v2.json',freeze)
    db.raw_sql("SELECT set_config('default_transaction_read_only','on',false),set_config('statement_timeout','120000',false)")
    for year in range(2008,2027):
        start=max(f'{year}-01-01','2008-11-01'); end=min(f'{year}-12-31','2026-02-28')
        query=f"SELECT permno,permco,dlycaldt AS date,dlyprc::float8 AS close,dlyret::float8 AS total_return,dlycap::float8*1000 AS market_cap,(abs(dlyprc)*dlyvol)::float8 AS dollar_volume,dlydelflg AS delisting FROM crsp_q_stock.dsf_v2 WHERE dlycaldt BETWEEN '{start}' AND '{end}' AND sharetype='NS' AND securitytype='EQTY' AND securitysubtype='COM' AND usincflg='Y' AND issuertype IN ('ACOR','CORP') AND primaryexch IN ('N','A','Q') ORDER BY permno,dlycaldt"
        prices=frame_cache(db,f'prices_{year}.parquet',query,['date'])
        print('PRICES_EXTRACTED',year,len(prices),flush=True)
        del prices;gc.collect()
    calendar=pd.DatetimeIndex(new_market.date).sort_values().unique()
    market=new_market.set_index('date').vwretd.astype(float)
    seen=set()
    for year in range(2009,2027):
        query=f"SELECT timestamp_utc,rp_story_id,rp_entity_id,rp_story_event_index,event_sentiment_score,event_similarity_days,topic,relevance FROM ravenpack_dj.rpa_djpr_equities_{year} WHERE country_code='US' AND entity_type='COMP' AND relevance=100"
        if year==2026:
            query+=" AND timestamp_utc < '2026-01-02'"
        events=frame_cache(db,f'news_events_{year}.parquet',query,[])
        if year==2026:
            events=events.loc[pd.to_datetime(events.timestamp_utc).lt('2026-01-02')]
        identities=events.rp_story_id+':'+events.rp_entity_id
        events=events.loc[~identities.isin(seen)].copy()
        seen.update(identities)
        daily,audit=adapter.normalize_rpa_events(events,links,calendar)
        daily.to_parquet(OUT/f'news_daily_{year}.parquet',index=False)
        save_json(f'news_audit_{year}.json',audit)
        print('NEWS_AGGREGATED',year,len(daily),flush=True)
        del events,daily;gc.collect()
    for year in range(2010,2026):
        prepare_year(year,adapter,links,calendar,market)
        gc.collect()
    save_json('stage_status.json',{'status':'data-prepared; fitting-not-started','next':'quality gate and frozen development selection','real_outputs':'private'})
    print('REAL_DATA_PREPARED_NO_FIT_YET',flush=True)
