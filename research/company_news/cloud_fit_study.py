"""Private, deterministic evaluation. Never print licensed values to an LLM UI."""
from pathlib import Path
import datetime
import hashlib
import json
import sys

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


def write_json(path, value):
    path.write_text(json.dumps(value,default=str,indent=2))


def portfolio(predictions, prices, calendar, cost_bps, borrow_bps, delay, attribution=False):
    assets=pd.Index(sorted(predictions.permno.unique()))
    returns=prices.loc[prices.permno.isin(assets)].pivot(index='date',columns='permno',values='total_return').reindex(index=calendar,columns=assets)
    closes=prices.loc[prices.permno.isin(assets)].pivot(index='date',columns='permno',values='close').reindex(index=calendar,columns=assets)
    terminal=np.full(len(assets),len(calendar),dtype=int)
    for permno, firm in prices.loc[prices.permno.isin(assets)].groupby('permno'):
        last=firm.sort_values('date').iloc[-1]
        if last.delisting=='Y' and pd.notna(last.total_return):
            position=calendar.get_indexer([last.date])[0]
            terminal[assets.get_loc(permno)]=position
            returns.loc[calendar>last.date,permno]=0
    targets=np.zeros(returns.shape,dtype=float)
    rejected_entries=0
    close_values=closes.to_numpy(dtype=float,na_value=np.nan)
    for date, group in predictions.groupby('date'):
        group=group.sort_values(['B2','permno'])
        count=max(1,int(np.floor(len(group)*.1)))
        start=calendar.get_indexer([date])[0]+1+delay
        if len(group)<2*count or start<=0 or start+5>=len(calendar):
            continue
        weights=np.zeros(len(assets))
        longs=assets.get_indexer(group.tail(count).permno)
        shorts=assets.get_indexer(group.head(count).permno)
        weights[longs]=1/count/5
        weights[shorts]=-1/count/5
        available=np.isfinite(close_values[start])&(close_values[start]>0)&(start<terminal)
        rejected_entries+=int(((weights!=0)&~available).sum())
        weights[~available]=0
        targets[start:start+5]+=weights
    positions=np.arange(len(calendar))[:,None]
    targets[positions>=terminal[None,:]]=0
    values=returns.to_numpy(dtype=float,na_value=np.nan)
    previous=np.zeros(len(assets))
    rows=[]
    wealth=1.
    gross_attribution=np.zeros(len(assets))
    borrow_attribution=np.zeros(len(assets))
    cost_attribution=np.zeros(len(assets))
    maximum_weight=np.zeros(len(assets))
    for position,date in enumerate(calendar):
        observed=values[position]
        if np.isnan(observed[previous!=0]).any():
            raise ValueError('Missing held-security return; no silent imputation or hindsight deletion')
        observed=np.nan_to_num(observed)
        gross=float(previous@observed)
        borrow=float(-np.minimum(previous,0).sum())*borrow_bps/10000/252
        equity=1+gross-borrow
        if equity<=0:
            raise ValueError('Equity exhausted')
        drifted=previous*(1+observed)/equity
        drifted[position>=terminal]=0
        desired=targets[position]
        cost=0.
        for _ in range(100):
            updated=cost_bps/10000*float(np.abs(desired*(1-cost)-drifted).sum())
            if abs(updated-cost)<1e-14:
                cost=updated
                break
            cost=updated
        traded=float(np.abs(desired*(1-cost)-drifted).sum())
        if attribution:
            gross_attribution+=wealth*previous*observed
            borrow_attribution+=wealth*(-np.minimum(previous,0))*borrow_bps/10000/252
            cost_attribution+=wealth*equity*cost_bps/10000*np.abs(desired*(1-cost)-drifted)
            maximum_weight=np.maximum(maximum_weight,np.abs(previous))
        rows.append({'date':date,'gross':gross,'borrow':borrow,'trading_cost':equity*cost,'one_way_turnover':traded,'net':equity*(1-cost)-1,'gross_exposure':float(np.abs(desired).sum()),'net_exposure':float(desired.sum())})
        wealth*=equity*(1-cost)
        previous=desired.copy()
    ledger=pd.DataFrame(rows)
    if attribution:
        assigned=gross_attribution-borrow_attribution-cost_attribution
        if not np.isclose(assigned.sum(),wealth-1,rtol=1e-9,atol=1e-10):
            raise ValueError('Security attribution does not reconcile with book equity')
        ledger.attrs['security_attribution']=pd.DataFrame({'permno':assets,'gross_initial_capital':gross_attribution,'borrow_initial_capital':borrow_attribution,'cost_initial_capital':cost_attribution,'net_initial_capital':assigned,'maximum_absolute_weight':maximum_weight})
    return ledger,rejected_entries


def execute(study):
    root=study.OUT
    output=root/'evaluation'
    if not (root/'quality_gate.json').exists():
        raise ValueError('Coverage quality gate must precede predictive fitting')
    output.mkdir(exist_ok=False)
    write_json(output/'evaluation_protocol.json',{'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'frozen before predictive outcomes','code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'primary':'date-equal-weight MSE B0 minus B2; adjusted five-session return',
        'alpha_grid':[.1,1.,10.],'blocks':20,'resamples':2000,
        'portfolio_ranking':'all confirmation rows with usable baseline features and calendar-complete horizon; never filtered by realized target availability',
        'entry_rejection':'observe entry-date close; no redistribution of rejected weights',
        'delisting':'valid final CIZ return then cash; no manual second DLRET; no artificial order cost for automatic cash settlement',
        'missing_returns':'stop P&L rather than impute; retain unavailable scenarios',
        'event_groups':'training 30/70 percentiles of observed novelty; descriptive event paths',
        'publication':'private; no license grant for raw, row-level, model or aggregate outputs'})
    panel=pd.concat([pd.read_parquet(root/f'panel_checked_{year}.parquet') for year in range(2010,2026)],ignore_index=True)
    if panel.duplicated(['permno','date']).any() or panel.duplicated(['permco','date']).any():
        raise ValueError('Universe is not one security per company-session')
    panel=panel.sort_values(['date','permno']).reset_index(drop=True)
    metrics=[]; selections=[]; predictions=[]; contrasts=[]; ic=[]; annual=[]
    choices={}
    for horizon in [1,5,20]:
        for target in ['raw','adjusted']:
            label=f'{target}_{horizon}'
            usable=panel[study.BASE].notna().all(axis=1)
            valid=usable&panel[label].notna()
            train=panel.loc[valid&panel.date.between('2010-01-01','2017-12-31')&panel[f'end_{horizon}'].lt('2018-01-01')]
            validation=panel.loc[valid&panel.date.between('2018-01-01','2020-12-31')&panel[f'end_{horizon}'].lt('2021-01-01')]
            if min(len(train),len(validation))==0:
                raise ValueError('Empty development split')
            for name in ['B0','B1','B2']:
                scores=[]
                for alpha in [.1,1.,10.]:
                    fitted=study.model(name,alpha).fit(train,train[label])
                    scores.append((float(np.mean((validation[label]-fitted.predict(validation))**2)),alpha))
                _,alpha=min(scores)
                choices[(horizon,target,name)]=alpha
                selections.append({'horizon':horizon,'target':target,'model':name,'alpha':alpha,'development_scores':scores,'training_rows':len(train),'validation_rows':len(validation)})
            print('DEVELOPMENT_SELECTION_DONE',horizon,target,flush=True)
    write_json(output/'frozen_selection.json',{'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'selections':selections})
    for horizon in [1,5,20]:
        for target in ['raw','adjusted']:
            label=f'{target}_{horizon}'
            usable=panel[study.BASE].notna().all(axis=1)
            before=panel.loc[usable&panel[label].notna()&panel.date.lt('2021-01-01')&panel[f'end_{horizon}'].lt('2021-01-01')]
            confirmation=panel.loc[usable&panel.date.ge('2021-01-01')&panel[f'end_{horizon}'].lt('2026-01-01')]
            result=confirmation[['date','permno',label]].rename(columns={label:'target'}).copy()
            result['horizon']=horizon;result['target_type']=target
            for name in ['B0','B1','B2']:
                fitted=study.model(name,choices[(horizon,target,name)]).fit(before,before[label])
                result[name]=fitted.predict(confirmation)
                known=result.target.notna()
                mse=float(np.mean((result.loc[known,'target']-result.loc[known,name])**2))
                metrics.append({'horizon':horizon,'target':target,'model':name,'n_scored':int(known.sum()),'n_target_unavailable':int((~known).sum()),'mse_observation_weighted':mse})
                ranked=result.loc[known,['date','target',name]].copy()
                ranked[['target_rank','prediction_rank']]=ranked.groupby('date')[['target',name]].rank(method='average')
                daily_ic=ranked.groupby('date')[['target_rank','prediction_rank']].corr().iloc[0::2,-1]
                ic.append(pd.DataFrame({'date':daily_ic.index.get_level_values(0),'ic':daily_ic.values,'model':name,'horizon':horizon,'target':target}))
                for year, subset in result.loc[known].groupby(result.loc[known,'date'].dt.year):
                    annual.append({'year':int(year),'horizon':horizon,'target':target,'model':name,'n':len(subset),'mse':float(np.mean((subset.target-subset[name])**2))})
            known=result.target.notna()
            errors=result.loc[known].assign(difference=lambda data:(data.target-data.B0)**2-(data.target-data.B2)**2)
            daily=errors.groupby('date').difference.mean()
            contrasts.append({'horizon':horizon,'target':target,'date_equal_weight_mse_improvement':float(daily.mean()),'interval_95':study.paired_interval(daily)})
            predictions.append(result)
            print('CONFIRMATION_EVALUATION_DONE',horizon,target,flush=True)
    all_predictions=pd.concat(predictions,ignore_index=True)
    all_predictions.to_parquet(output/'predictions_private.parquet',index=False)
    pd.DataFrame(metrics).to_csv(output/'all_metrics_private.csv',index=False)
    pd.concat(ic,ignore_index=True).to_csv(output/'daily_ic_private.csv',index=False)
    pd.DataFrame(annual).to_csv(output/'all_years_private.csv',index=False)
    write_json(output/'paired_contrasts_private.json',contrasts)
    primary=all_predictions.loc[all_predictions.horizon.eq(5)&all_predictions.target_type.eq('adjusted')]
    assets=set(primary.permno)
    price_frames=[]
    for year in range(2021,2026):
        frame=pd.read_parquet(root/f'holding_prices_{year}.parquet')
        price_frames.append(frame.loc[frame.permno.isin(assets)])
    prices=pd.concat(price_frames,ignore_index=True)
    if prices.groupby(['permno','date'])[['total_return','close','delisting']].nunique(dropna=False).gt(1).any().any():
        raise ValueError('Conflicting overlapping holding-price vintages')
    prices=prices.drop_duplicates(['permno','date'])
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.loc[market.date.ge(primary.date.min()),'date'])
    scenarios=[]
    for delay in [0,1,2]:
        for cost in [0,5,10,20]:
            for borrow in [0,100,300]:
                record={'extra_delay':delay,'one_way_cost_bps':cost,'borrow_bps':borrow}
                try:
                    audit=delay==0 and cost==10 and borrow==100
                    ledger,rejected=portfolio(primary,prices,calendar,cost,borrow,delay,attribution=audit)
                    if audit:
                        ledger.attrs['security_attribution'].to_csv(output/'security_attribution_private.csv',index=False)
                    ledger.to_csv(output/f'ledger_delay{delay}_cost{cost}_borrow{borrow}_private.csv',index=False)
                    record.update(status='computed',total_net=float((1+ledger.net).prod()-1),mean_one_way_turnover=float(ledger.one_way_turnover.mean()),entry_orders_rejected=rejected)
                    for year, group in ledger.groupby(ledger.date.dt.year):
                        record[f'net_{year}']=float((1+group.net).prod()-1)
                except ValueError as error:
                    record.update(status='not-estimable',reason=str(error))
                scenarios.append(record)
        print('IMPLEMENTATION_SCENARIOS_DONE',delay,flush=True)
    pd.DataFrame(scenarios).to_csv(output/'all_cost_scenarios_private.csv',index=False)
    primary_result=next(record for record in contrasts if record['horizon']==5 and record['target']=='adjusted')
    lower,upper=primary_result['interval_95']
    judgment=('The interval is positive under this retrospective archive design.' if lower>0 else 'The primary interval does not establish an improvement over B0.')
    report=['# Company News — Private Historical Archive Study','',
        '**Private: data-derived metrics and figures are not cleared for public dissemination.**','',
        'Wharton Research Data Services (WRDS) was used in preparing this company-news research. This service and the data available thereon constitute valuable intellectual property and trade secrets of WRDS and/or its third-party suppliers.','',
        '## Primary finding','',f"Date-equal-weight MSE(B0) minus MSE(B2): {primary_result['date_equal_weight_mse_improvement']:.10g}; paired date-block 95% interval [{lower:.10g}, {upper:.10g}].",'',judgment,'',
        'This is a retrospective historical archive test with vendor receipt as an availability proxy. Original publication time, scoring completion and original historical scoring vintages are not established. A positive interval is not causal evidence or demonstrated tradable alpha. B1 also adds current news/missingness indicators, so its increment is a news-feature bundle.','',
        '## Complete outputs','',
        '- All 18 predictive rows, both targets, three horizons and every confirmation year are retained.',
        '- All 36 cost/borrowing/delay scenarios are retained, including not-estimable cases.',
        '- Missing held-security returns stop the implementation ledger; they do not delete trades using hindsight.',
        '- The profile and public FOMC result remain separate from these private company-news outcomes.','',
        '## Remaining acceptance work','',
        'Explanatory panel analysis, novelty event paths, exposure/concentration attribution and final economic interpretation require their own completed checks. Source score vintages, feed completeness and dissemination permission remain limitations. This report does not mark the entire project validated.']
    (output/'REPORT_PRIVATE.md').write_text('\n'.join(report))
    write_json(output/'manifest.json',{'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'predictive-evaluation-executed; research-acceptance-incomplete','outputs':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file()},'empirical_values_export_to_llm':'not authorized; status checks only'})
    print('PRIVATE_PREDICTIVE_EVALUATION_FINISHED',flush=True)
