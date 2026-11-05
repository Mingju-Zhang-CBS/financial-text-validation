"""Private descriptive diagnostics. All empirical outputs stay in WRDS Cloud."""
from pathlib import Path
import hashlib
import json
import datetime
import numpy as np
import pandas as pd


def within(values, firm, date, tolerance=1e-10):
    result=np.asarray(values,dtype=float).copy()
    for _ in range(200):
        change=0.
        for codes in [firm,date]:
            count=np.bincount(codes)
            means=np.column_stack([np.bincount(codes,weights=result[:,j])/count for j in range(result.shape[1])])
            change=max(change,float(np.max(np.abs(means))))
            result-=means[codes]
        if change<tolerance:
            return result
    raise ValueError('Two-way within transformation did not converge')


def hac_meat(scores, lags=20):
    scores=np.asarray(scores,dtype=float)
    meat=scores.T@scores
    for lag in range(1,min(lags,len(scores)-1)+1):
        cross=scores[lag:].T@scores[:-lag]
        meat+=(1-lag/(lags+1))*(cross+cross.T)
    return meat


def panel_analysis(panel, output, base):
    columns=base+['sentiment','novelty','sentiment_novelty','sentiment_coverage']
    development=panel.loc[panel.date.lt('2021-01-01')]
    scale=development[columns].std().replace(0,np.nan)
    center=development[columns].mean()
    sample=panel.loc[panel.date.ge('2021-01-01')&panel[columns+['adjusted_5']].notna().all(axis=1)].copy()
    if scale.isna().any() or sample.empty:
        raise ValueError('Explanatory sample or development scale unavailable')
    firm=pd.factorize(sample.permco,sort=True)[0]
    date=pd.factorize(sample.date,sort=True)[0]
    transformed=within(np.column_stack([sample.adjusted_5,(sample[columns]-center)/scale]),firm,date)
    y,x=transformed[:,0],transformed[:,1:]
    if np.linalg.matrix_rank(x)<len(columns):
        raise ValueError('Prespecified explanatory design is rank deficient')
    inverse=np.linalg.inv(x.T@x)
    coefficient=inverse@(x.T@y)
    residual=y-x@coefficient
    scores=x*residual[:,None]
    def grouped(codes):
        return np.column_stack([np.bincount(codes,weights=scores[:,j]) for j in range(scores.shape[1])])
    by_firm,by_date=grouped(firm),grouped(date)
    cluster=inverse@(by_firm.T@by_firm+by_date.T@by_date-scores.T@scores)@inverse
    time_hac=inverse@hac_meat(by_date)@inverse
    cluster_variance=np.diag(cluster)
    pd.DataFrame({'feature':columns,'coefficient_per_development_sd':coefficient,
        'two_way_cluster_se':np.sqrt(np.where(cluster_variance>=0,cluster_variance,np.nan)),
        'date_hac20_se':np.sqrt(np.maximum(np.diag(time_hac),0))}).to_csv(output/'explanatory_panel_private.csv',index=False)
    return {'sample_rows':len(sample),'firm_count':len(np.unique(firm)),'date_count':len(np.unique(date)),
        'design':'Confirmation-period firm/date fixed effects; coefficients per pre-2021 feature SD; no predictive selection from these estimates',
        'inference':'Asymptotic two-way firm/date cluster and Bartlett date-score HAC20; secondary descriptive inference, no causal interpretation or multiplicity-adjusted discovery'}


def event_paths(panel, prices, market, output):
    development=panel.loc[panel.date.lt('2021-01-01')]
    novelty=development.loc[development.news_count.gt(0),'novelty'].dropna().quantile([.3,.7]).to_numpy()
    attention=development.past_coverage.dropna().quantile([.3,.7]).to_numpy()
    events=panel.loc[panel.date.ge('2021-01-01')&panel.news_count.gt(0)&panel[['sentiment','novelty','past_coverage']].notna().all(axis=1)].copy()
    events['novelty_group']=np.where(events.novelty.le(novelty[0]),'low',np.where(events.novelty.ge(novelty[1]),'high','middle'))
    events['attention_group']=np.where(events.past_coverage.le(attention[0]),'low',np.where(events.past_coverage.ge(attention[1]),'high','middle'))
    events['sentiment_group']=np.where(events.sentiment.lt(0),'negative',np.where(events.sentiment.gt(0),'positive','neutral'))
    calendar=pd.DatetimeIndex(market.date)
    assets=pd.Index(sorted(events.permno.unique()))
    matrix=prices.pivot(index='date',columns='permno',values='total_return').reindex(index=calendar,columns=assets)
    # Match the main study's explicit terminal-payoff-to-cash assumption.
    for permno,group in prices.groupby('permno'):
        last=group.sort_values('date').iloc[-1]
        if permno in assets and last.delisting=='Y' and pd.notna(last.total_return):
            matrix.loc[calendar>last.date,permno]=0.
    values=matrix.to_numpy(dtype=float,na_value=np.nan)
    benchmark=market.vwretd.to_numpy(dtype=float,na_value=np.nan)
    row=calendar.get_indexer(events.date)
    column=assets.get_indexer(events.permno)
    stock=np.ones(len(events)); broad=np.ones(len(events)); rows=[]
    groups=['novelty_group','attention_group','sentiment_group']
    for offset in range(21):
        positions=row+offset
        available=(positions>=0)&(positions<len(calendar))
        increment=np.full(len(events),np.nan); market_increment=increment.copy()
        increment[available]=values[positions[available],column[available]]
        market_increment[available]=benchmark[positions[available]]
        stock*=1+increment; broad*=1+market_increment
        events['path']=stock-broad
        for keys,subset in events.groupby(groups,observed=True):
            known=subset.path.notna()
            daily=subset.loc[known].groupby('date').path.agg(['sum','count']).reindex(calendar,fill_value=0)
            count=float(daily['count'].sum())
            mean=float(daily['sum'].sum()/count) if count else np.nan
            score=(daily['sum']-mean*daily['count']).to_numpy()[:,None]
            se=float(np.sqrt(max(hac_meat(score)[0,0],0))/count) if count else np.nan
            rows.append(dict(zip(groups,keys),offset=offset,mean_market_adjusted_path=mean,
                lower_95=mean-1.96*se,upper_95=mean+1.96*se,events=len(subset),observed=int(known.sum()),missing=int((~known).sum())))
    result=pd.DataFrame(rows).set_index(groups+['offset'])
    complete=pd.MultiIndex.from_product([['low','middle','high'],['low','middle','high'],['negative','neutral','positive'],range(21)],names=groups+['offset'])
    result=result.reindex(complete).reset_index()
    result[['events','observed','missing']]=result[['events','observed','missing']].fillna(0).astype(int)
    result.to_csv(output/'all_event_paths_private.csv',index=False)
    return result,{'novelty_thresholds':novelty.tolist(),'past_coverage_thresholds':attention.tolist(),
        'clock':'offset 0 includes the news session return; all paths begin at the prior close and are descriptive, not signal-following strategy P&L',
        'limitations':'Overlapping news events are retained; missing paths counted at every offset; HAC20 date-score intervals are descriptive; receipt proxy is not verified publication time'}


def execute(study):
    root=study.OUT
    evaluation=root/'evaluation'
    assert (evaluation/'manifest.json').exists(), 'Predictive stage must finish first'
    output=root/'diagnostics'
    output.mkdir(exist_ok=False)
    (output/'frozen_diagnostics.json').write_text(json.dumps({'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'timing':'Written without inspecting empirical outcomes; detailed descriptive design supplements the original high-level protocol',
        'panel_target':'five-session market-adjusted return; confirmation 2021-2025',
        'event_groups':'30/70 development quantiles; all low/middle/high novelty and coverage groups, all sentiment signs; offsets 0-20',
        'economic_reference':'delay0,10bps one-way,100bps annual borrow; no result-based scenario choice'},indent=2))
    panel=pd.concat([pd.read_parquet(root/f'panel_checked_{y}.parquet') for y in range(2010,2026)],ignore_index=True)
    details={}
    try:
        details['panel']=panel_analysis(panel,output,study.BASE)
    except ValueError as error:
        details['panel']={'status':'not-estimable','reason':str(error)}
    print('PRIVATE_EXPLANATORY_STAGE_FINISHED',flush=True)
    prices=pd.concat([pd.read_parquet(root/f'holding_prices_{y}.parquet') for y in range(2020,2026)],ignore_index=True)
    if prices.groupby(['permno','date'])[['total_return','close','delisting']].nunique(dropna=False).gt(1).any().any():
        raise ValueError('Inconsistent price-cache vintages')
    prices=prices.drop_duplicates(['permno','date'])
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet').sort_values('date')
    paths,details['events']=event_paths(panel,prices,market,output)
    print('PRIVATE_EVENT_PATH_STAGE_FINISHED',flush=True)
    ledger_path=evaluation/'ledger_delay0_cost10_borrow100_private.csv'
    attribution_path=evaluation/'security_attribution_private.csv'
    if ledger_path.exists() and attribution_path.exists():
        ledger=pd.read_csv(ledger_path,parse_dates=['date'])
        attribution=pd.read_csv(attribution_path)
        total=float((1+ledger.net).prod()-1)
        if not np.isclose(attribution.net_initial_capital.sum(),total,atol=1e-9):
            raise ValueError('Published attribution table does not reconcile')
        joined=ledger.merge(market,on='date',validate='one_to_one').dropna(subset=['net','vwretd'])
        design=np.column_stack([np.ones(len(joined)),joined.vwretd])
        inverse=np.linalg.inv(design.T@design); beta=inverse@(design.T@joined.net)
        scores=design*(joined.net-design@beta).to_numpy()[:,None]
        standard_error=np.sqrt(np.maximum(np.diag(inverse@hac_meat(scores)@inverse),0))
        absolute=attribution.net_initial_capital.abs().sort_values(ascending=False)
        details['economics']={'status':'computed','total_net':total,'market_intercept_daily':beta[0],
            'market_beta':beta[1],'market_intercept_hac20_se':standard_error[0],'market_beta_hac20_se':standard_error[1],
            'top10_absolute_contribution_share':float(absolute.head(10).sum()/absolute.sum()) if absolute.sum() else None,
            'maximum_security_weight':float(attribution.maximum_absolute_weight.max()),
            'risk_scope':'Market-only descriptive exposure; no claim of size/value/industry/factor neutrality; intercept is not established risk-adjusted alpha'}
    else:
        details['economics']={'status':'not-estimable','reason':'Fixed reference implementation scenario or attribution unavailable; all failed scenarios remain in evaluation outputs'}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(1,2,figsize=(11,4),sharey=True)
    for axis,sign in zip(axes,['negative','positive']):
        for novelty in ['low','middle','high']:
            selected=paths.loc[paths.sentiment_group.eq(sign)&paths.attention_group.eq('middle')&paths.novelty_group.eq(novelty)]
            axis.plot(selected.offset,selected.mean_market_adjusted_path,label=novelty)
        axis.axhline(0,color='grey',linewidth=.7);axis.set_title(f'{sign} sentiment; middle prior coverage')
        axis.set_xlabel('Sessions from news day (0 includes event-day reaction)');axis.legend(title='Novelty')
    axes[0].set_ylabel('Cumulative stock minus market return')
    figure.tight_layout();figure.savefig(output/'event_paths_PRIVATE.png',dpi=160);plt.close(figure)
    (output/'diagnostics_private.json').write_text(json.dumps(details,indent=2,default=float))
    report=['# Private supplementary diagnostics','',
        'Not cleared for public dissemination. Interpret with evaluation/REPORT_PRIVATE.md and the frozen protocol.','',
        'Explanatory panel estimates are associations after firm/date demeaning. They cannot establish causal investor attention or select the prediction model.',
        'Event-day paths begin before the signal and are not strategy returns. All defined groups and missing-path counts remain in the CSV.',
        'Market exposure is a limited diagnostic, not a comprehensive factor-neutrality claim. Security contributions reconcile in units of initial capital.',
        'Read diagnostics_private.json, explanatory_panel_private.csv, all_event_paths_private.csv, event_paths_PRIVATE.png and the complete predictive/cost output set.',
        'Final interpretation and permission to publish real-data outputs require review; software completion alone does not grant either.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report))
    (output/'manifest.json').write_text(json.dumps({'status':'supplementary-diagnostics-executed; human-interpretation-and-dissemination-review-pending',
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('PRIVATE_DIAGNOSTICS_FINISHED',flush=True)
