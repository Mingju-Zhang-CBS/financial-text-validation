"""Version-3 valuation assumptions and executable-quote constrained book.

This is a separately specified replay of frozen predictions, not a silent repair
of v2. Missing economic returns still stop the book unless a certified CRSP
bridge explicitly supplies stale valuation marks and its later complete payoff.
"""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

_spec=importlib.util.spec_from_file_location('return_reconciliation_v3',Path(__file__).with_name('return_reconciliation.py'))
reconciliation=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(reconciliation)


def certified_stale_marks(frame, calendar):
    frame=frame.sort_values(['permno','date']).reset_index(drop=True).copy()
    if frame.duplicated(['permno','date']).any():
        raise ValueError('Duplicate valuation key')
    if 'resolved_return' not in frame:
        frame['resolved_return']=frame.total_return
        frame['return_provenance']='original-crsp'
    for _,group in frame.groupby('permno',sort=False):
        indices=group.index.to_numpy();missing=group.resolved_return.isna().to_numpy()
        start=0
        while start<len(indices):
            if not missing[start]:
                start+=1;continue
            end=start
            while end<len(indices) and missing[end]:
                end+=1
            gap=indices[start:end]
            valid=start>0 and end<len(indices)
            if valid:
                recovery=indices[end];last=indices[start-1]
                valid=frame.loc[gap,'return_missing_flag'].eq('MP').fillna(False).all()
                valid=valid and frame.loc[gap,'delisting'].eq('N').fillna(False).all()
                quote_column='execution_close' if 'execution_close' in frame else 'close'
                no_quote=(frame.loc[gap,quote_column].isna()|frame.loc[gap,'trading_status'].isin(['H','S']))
                valid=valid and no_quote.all() and frame.loc[gap,'trading_status'].isin(['A','H','S']).all()
                valid=valid and pd.notna(frame.at[last,'close']) and frame.at[last,'close']>0
                valid=valid and reconciliation.validate_bridge(calendar,frame.at[last,'date'],
                    frame.at[recovery,'date'],frame.at[recovery,'previous_price_date'],
                    frame.at[recovery,'return_duration_flag'])
                valid=valid and pd.notna(frame.at[recovery,'resolved_return'])
                valid=valid and np.array_equal(pd.DatetimeIndex(frame.loc[indices[start:end+1],'date']).to_numpy(),
                    pd.DatetimeIndex(calendar)[pd.DatetimeIndex(calendar).get_loc(frame.at[last,'date'])+1:
                        pd.DatetimeIndex(calendar).get_loc(frame.at[recovery,'date'])+1].to_numpy())
            if valid:
                frame.loc[gap,'resolved_return']=0.
                frame.loc[gap,'return_provenance']='stale-valuation-mark; later-certified-crsp-bridge'
            start=end
    # A return which spans several sessions cannot be used as a daily payoff
    # after an alternate feed has already valued those sessions independently.
    for _,group in frame.groupby('permno',sort=False):
        for index,row in group.loc[group.return_duration_flag.astype(str).str.fullmatch(r'P[1-9]')].iterrows():
            if frame.at[index,'return_provenance']!='original-crsp':
                continue
            covered=group.loc[group.date.gt(row.previous_price_date)&group.date.lt(row.date)]
            certified=covered.return_provenance.eq('stale-valuation-mark; later-certified-crsp-bridge').all()
            if covered.empty or not certified:
                frame.at[index,'resolved_return']=np.nan
                frame.at[index,'return_provenance']='unreconciled-multi-session-payoff'
    return frame


def rebalance(drifted, planned, tradable, cost_rate):
    """Locked positions keep dollar holdings; active legs respect remaining budget."""
    if not 0<=cost_rate<.1:
        raise ValueError('Invalid transaction cost rate')
    locked=~tradable
    cost=0.
    for _ in range(300):
        actual=planned.copy()
        actual[locked]=drifted[locked]/(1-cost)
        for sign in [1,-1]:
            budget=max(0.,np.maximum(sign*planned,0).sum()-np.maximum(sign*actual[locked],0).sum())
            leg=tradable&(sign*planned>0)
            requested=float((sign*planned[leg]).sum())
            if requested:
                actual[leg]*=min(1.,budget/requested)
        trades=actual*(1-cost)-drifted
        updated=cost_rate*float(np.abs(trades[tradable]).sum())
        if abs(updated-cost)<1e-13:
            if not np.allclose(trades[locked],0.,atol=1e-12):
                raise ValueError('Unquoted position traded')
            return actual,updated,float(np.abs(trades).sum())
        cost=updated
    raise ValueError('Constrained cost solver did not converge')


def prepare(predictions, prices, calendar, delay):
    calendar=pd.DatetimeIndex(calendar);assets=pd.Index(sorted(predictions.permno.unique()))
    if prices.duplicated(['permno','date']).any():
        raise ValueError('Conflicting valuation records')
    def matrix(column):
        return prices.pivot(index='date',columns='permno',values=column).reindex(index=calendar,columns=assets)
    returns=matrix('resolved_return')
    quote_column='execution_close' if 'execution_close' in prices else 'close'
    close=matrix(quote_column).to_numpy(dtype=float,na_value=np.nan)
    trading=matrix('trading_status').eq('A').fillna(False).to_numpy(dtype=bool)
    tradable=np.isfinite(close)&(close>0)&trading
    terminal=np.full(len(assets),len(calendar),dtype=int)
    for permno,group in prices.loc[prices.permno.isin(assets)].groupby('permno'):
        last=group.sort_values('date').iloc[-1]
        if last.delisting=='Y' and pd.notna(last.resolved_return):
            terminal[assets.get_loc(permno)]=calendar.get_indexer([last.date])[0]
            returns.loc[calendar>last.date,permno]=0.
    targets=np.zeros(returns.shape);rejected=0
    for date,group in predictions.groupby('date'):
        group=group.sort_values(['B2','permno']);count=max(1,int(len(group)*.1))
        start=calendar.get_indexer([date])[0]+1+delay
        if len(group)<2*count or start<=0 or start+5>=len(calendar):
            continue
        weights=np.zeros(len(assets));weights[assets.get_indexer(group.tail(count).permno)]=1/count/5
        weights[assets.get_indexer(group.head(count).permno)]=-1/count/5
        unavailable=~tradable[start]|(start>=terminal)
        rejected+=int(((weights!=0)&unavailable).sum());weights[unavailable]=0
        targets[start:start+5]+=weights
    targets[np.arange(len(calendar))[:,None]>=terminal]=0
    values=returns.to_numpy(dtype=float,na_value=np.nan)
    for array in [values,targets,tradable,terminal]:
        array.setflags(write=False)
    return {'calendar':calendar,'assets':assets,'values':values,'targets':targets,
        'tradable':tradable,'terminal':terminal,'rejected':rejected,'delay':delay}


def portfolio(predictions, prices, calendar, cost_bps, borrow_bps, delay, prepared=None):
    state=prepare(predictions,prices,calendar,delay) if prepared is None else prepared
    if state['delay']!=delay or not state['calendar'].equals(pd.DatetimeIndex(calendar)):
        raise ValueError('Prepared portfolio clock mismatch')
    if not state['assets'].equals(pd.Index(sorted(predictions.permno.unique()))):
        raise ValueError('Prepared portfolio universe mismatch')
    calendar=state['calendar'];assets=state['assets'];values=state['values']
    targets=state['targets'];tradable=state['tradable'];terminal=state['terminal'];rejected=state['rejected']
    previous=np.zeros(len(assets));wealth=1.;rows=[];contribution=np.zeros(len(assets))
    for position,date in enumerate(calendar):
        observed=values[position]
        if not np.isfinite(observed[previous!=0]).all():
            raise ValueError('Unresolved held return; v3 cannot complete this scenario')
        observed=np.where(np.isfinite(observed),observed,0.)
        if (observed<-1).any():
            raise ValueError('Invalid total return')
        asset_gross=previous*observed
        asset_borrow=-np.minimum(previous,0)*borrow_bps/10000/252
        equity=1+asset_gross.sum()-asset_borrow.sum()
        if equity<=0:
            raise ValueError('Equity exhausted')
        drifted=previous*(1+observed)/equity
        drifted[position>=terminal]=0.
        active=tradable[position]&(position<terminal)
        desired,cost,turnover=rebalance(drifted,targets[position],active,cost_bps/10000)
        trades=desired*(1-cost)-drifted
        asset_cost=equity*cost_bps/10000*np.abs(trades)
        contribution+=wealth*(asset_gross-asset_borrow-asset_cost)
        net=equity*(1-cost)-1
        rows.append({'date':date,'net':float(net),'gross':float(asset_gross.sum()),
            'borrow':float(asset_borrow.sum()),'trading_cost':float(equity*cost),
            'one_way_turnover':turnover,'gross_exposure':float(np.abs(desired).sum()),
            'net_exposure':float(desired.sum()),'locked_gross_exposure':float(np.abs(desired[~active]).sum()),
            'unquoted_traded_notional':float(np.abs(trades[~active]).sum())})
        wealth*=1+net;previous=desired
    if not np.isclose(contribution.sum(),wealth-1,atol=1e-9,rtol=1e-9):
        raise ValueError('V3 contribution reconciliation failed')
    if np.any(previous!=0):
        raise ValueError('Unliquidated ending positions; ending value is not cash-realized')
    result=pd.DataFrame(rows)
    result.attrs['security_attribution']=pd.DataFrame({'permno':assets,'net_initial_capital':contribution})
    return result,rejected
