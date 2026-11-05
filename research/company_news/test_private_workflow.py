"""Full evaluation and diagnostics with invented inputs only."""
import importlib.util
from pathlib import Path
import json
import numpy as np
import pandas as pd


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_complete_private_workflow_with_synthetic_inputs(tmp_path):
    study=load('synthetic_study','cloud_real_study.py')
    fit=load('synthetic_fit','cloud_fit_study.py')
    diagnostics=load('synthetic_diagnostics','cloud_diagnostics.py')
    study.ROOT=tmp_path;study.OUT=tmp_path/'private_archive_v2';study.OUT.mkdir()
    (study.OUT/'quality_gate.json').write_text('{}')
    calendar=pd.bdate_range('2009-01-01','2026-02-28')
    generator=np.random.default_rng(713)
    market=pd.DataFrame({'date':calendar,'vwretd':generator.normal(0,.003,len(calendar))})
    market.to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    prices=pd.DataFrame([(date,permno) for date in calendar for permno in [1,2,3,4]],columns=['date','permno'])
    prices['total_return']=pd.Series(generator.normal(0,.01,len(prices)),dtype='Float64')
    prices['close']=pd.Series(10.,index=prices.index,dtype='Float64');prices['delisting']='N'
    for year in range(2010,2026):
        dates=calendar[calendar.year==year][:30]
        panel=pd.DataFrame([(date,permno,permno) for date in dates for permno in [1,2,3,4]],columns=['date','permno','permco'])
        for column in study.BASE+['sentiment','novelty','sentiment_novelty','sentiment_coverage']:
            panel[column]=generator.normal(size=len(panel))
        panel['novelty']=generator.uniform(size=len(panel));panel['past_coverage']=generator.uniform(0,5,len(panel))
        panel['sentiment_novelty']=panel.sentiment*panel.novelty
        panel['sentiment_coverage']=panel.sentiment*np.log1p(panel.past_coverage)
        panel['has_news']=True;panel['sentiment_missing']=False;panel['novelty_missing']=0.;panel['news_count']=1;panel['event_type']='earnings'
        for horizon in [1,5,20]:
            panel[f'end_{horizon}']=calendar[calendar.get_indexer(panel.date)+horizon+1]
            for target in ['raw','adjusted']:
                panel[f'{target}_{horizon}']=generator.normal(0,.01,len(panel))
        if year==2021:
            panel.loc[0,'adjusted_5']=np.nan
        panel.to_parquet(study.OUT/f'panel_checked_{year}.parquet',index=False)
        if year>=2020:
            prices.loc[prices.date.between(f'{year}-01-01',f'{year+1}-02-28')].to_parquet(study.OUT/f'holding_prices_{year}.parquet',index=False)
    fit.execute(study)
    output=study.OUT/'evaluation'
    assert len(pd.read_csv(output/'all_metrics_private.csv'))==18
    assert len(pd.read_csv(output/'all_cost_scenarios_private.csv'))==36
    assert len(json.loads((output/'frozen_selection.json').read_text())['selections'])==18
    predicted=pd.read_parquet(output/'predictions_private.parquet')
    assert predicted.loc[predicted.horizon.eq(5)&predicted.target_type.eq('adjusted'),'target'].isna().sum()==1
    assert (output/'security_attribution_private.csv').exists()
    diagnostics.execute(study)
    assert (study.OUT/'diagnostics'/'manifest.json').exists()
    assert (study.OUT/'diagnostics'/'event_paths_PRIVATE.png').exists()
    assert len(pd.read_csv(study.OUT/'diagnostics'/'all_event_paths_private.csv'))==27*21
    finalize=load('synthetic_finalize','cloud_finalize.py')
    finalize.execute(study)
    assert (study.OUT/'final_report'/'manifest.json').exists()
    assert json.loads((study.OUT/'final_report'/'manifest.json').read_text())['commercial_data_publication_authorized'] is False
