"""Private terminal-quote sensitivity; never an observed cash-settlement claim."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def terminal_marks(prices, events, distributions, calendar, multiplier=1.):
    """Keep raw observations intact elsewhere; create a declared valuation scenario.

    PRCF is a final price, not a cash dividend. Settlement at that quote is an
    explicit sensitivity assumption. It is never an executable closing order.
    """
    if multiplier not in {.5,1.,1.5}:
        raise ValueError('Unspecified terminal-price sensitivity')
    calendar=pd.DatetimeIndex(calendar)
    result=prices.copy();audits=[];additions=[]
    if result.duplicated(['permno','date']).any():
        raise ValueError('Duplicate input valuation')
    for permno,group in result.groupby('permno',sort=False):
        group=group.sort_values('date');last=group.iloc[-1]
        if last.delisting!='Y' or pd.notna(last.resolved_return):
            continue
        row={'permno':permno,'terminal_date':last.date,'status':'rejected'}
        candidates=events.loc[events.permno.eq(permno)&pd.to_datetime(events.deldlydt).eq(last.date)]
        if len(candidates)!=1:
            row['reason']='missing-or-ambiguous-exact-daily-event';audits.append(row);continue
        event=candidates.iloc[0]
        anchor_date=pd.Timestamp(event.delistingdt)
        anchors=group.loc[group.date.eq(anchor_date)]
        if len(anchors)!=1:
            row['reason']='last-trading-price-date-not-found';audits.append(row);continue
        anchor=anchors.iloc[0]
        anchor_price=float(event.deldtprc) if pd.notna(event.deldtprc) else np.nan
        if not (np.isfinite(anchor_price) and anchor_price>0 and pd.notna(anchor.close)
                and np.isclose(float(anchor.close),anchor_price,atol=1e-6,rtol=1e-5)):
            row['reason']='unreconciled-last-trading-price';audits.append(row);continue
        # Do not join across a previous unresolved corporate action or gap.
        if pd.isna(anchor.resolved_return):
            row['reason']='unresolved-anchor-valuation';audits.append(row);continue
        direct=float(event.delret) if pd.notna(event.delret) else np.nan
        if np.isfinite(direct) and direct>=-1:
            endpoint=pd.Timestamp(event.deldlydt);payoff=direct;method='direct-vendor-terminal-return'
        else:
            price=float(event.delnextprc) if pd.notna(event.delnextprc) else np.nan
            if event.delpaymenttype!='PRCF' or not np.isfinite(price) or price<=0 or pd.isna(event.delnextdt):
                row['reason']='no-qualified-final-price';audits.append(row);continue
            endpoint=pd.Timestamp(event.delnextdt)
            if endpoint<=anchor_date or endpoint<last.date:
                row['reason']='invalid-final-quote-timing';audits.append(row);continue
            relevant=distributions.loc[distributions.permno.eq(permno)
                &pd.to_datetime(distributions.disexdt).gt(anchor_date)
                &pd.to_datetime(distributions.disexdt).le(endpoint)]
            if not relevant.empty:
                row['reason']='intervening-corporate-action';audits.append(row);continue
            payoff=price*multiplier/anchor_price-1
            method='final-price-assumed-settlement; no-observed-execution'
        endpoint_position=calendar.searchsorted(endpoint)
        if endpoint_position>=len(calendar) or anchor_date not in calendar:
            row['reason']='endpoint-outside-fixed-buffer';audits.append(row);continue
        endpoint_session=calendar[endpoint_position]
        # No observed payoff may be overwritten or counted twice.
        tail=group.loc[group.date.gt(anchor_date)&group.date.le(endpoint_session)]
        if tail.resolved_return.notna().any() or group.date.gt(endpoint_session).any():
            row['reason']='conflicting-post-anchor-observation';audits.append(row);continue
        dates=calendar[(calendar>anchor_date)&(calendar<=endpoint_session)]
        for date in dates:
            existing=group.index[group.date.eq(date)]
            value=payoff if date==endpoint_session else 0.
            provenance=method if date==endpoint_session else 'stale-terminal-claim; assumed-later-settlement'
            if len(existing):
                index=existing[0]
                result.at[index,'resolved_return']=value
                result.at[index,'return_provenance']=provenance
                # Derived valuation view only. Never alter the source snapshot.
                result.at[index,'execution_close']=np.nan
                result.at[index,'trading_status']='D'
                result.at[index,'delisting']='Y' if date==endpoint_session else 'N'
            else:
                new={column:np.nan for column in result.columns}
                new.update(permno=permno,date=date,resolved_return=value,return_provenance=provenance,
                    trading_status='D',delisting='Y' if date==endpoint_session else 'N')
                additions.append(new)
        row.update(status='admitted-conditional-valuation',reason=method,anchor_date=anchor_date,
            final_quote_date=endpoint,recognition_session=endpoint_session,terminal_return=payoff,
            multiplier=multiplier,intermediate_mark='stale claim, not observed zero economic return')
        audits.append(row)
    if additions:
        result=pd.concat([result,pd.DataFrame(additions)],ignore_index=True)
    return result.sort_values(['permno','date']).reset_index(drop=True),pd.DataFrame(audits)


def execute(study,database,output_name='terminal_sensitivity_v4'):
    output=study.OUT/output_name
    if output.resolve().parent!=study.OUT.resolve():raise ValueError('Output outside private archive')
    output.mkdir(exist_ok=False)
    engine=load('terminal_book','implementation_v3.py')
    formatting=load('terminal_tables','cloud_finalize.py')
    prediction_path=study.OUT/'evaluation'/'predictions_private.parquet'
    source_path=study.OUT/'source_reconciliation_v3_local'/'resolved_valuation_PRIVATE.parquet'
    source_manifest=json.loads((source_path.parent/'manifest.json').read_text())
    assert sha(source_path)==source_manifest['outputs'][source_path.name]
    protocol={'id':'terminal-price-sensitivity-v4','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'amendment':'Retrospective data-failure remediation; frozen forecasts; no profitability-based selection',
        'prediction_sha256':sha(prediction_path),'source_sha256':sha(source_path),
        'endpoint':'exact CIZ PERMNO, delisting/daily date and last trading price; direct finite DelRet first, otherwise PRCF final quote with no intervening distribution',
        'timing':'lock economic claim from last trading session to final quote, mark stale in between, continue borrowing, recognize next session for a non-session quote date',
        'settlement_assumption':'PRCF final price is not cash. Convert to cash-equivalent value only as a declared terminal settlement sensitivity, no synthetic order or observed-execution claim',
        'price_multipliers':[.5,1.,1.5],'scenario_grid':{'delay':[0,1,2],'one_way_bps':[0,5,10,20],'borrow_bps':[0,100,300]},
        'failure':'Unknown entitlements, ambiguous dates/price anchors, any intervening distribution, unresolved anchor or gaps elsewhere still stop scenario',
        'code_sha256':{name:sha(Path(__file__).with_name(name)) for name in ['cloud_terminal_sensitivity.py','implementation_v3.py','return_reconciliation.py']}}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    prices=pd.read_parquet(source_path)
    pending=prices.loc[prices.delisting.eq('Y')&prices.resolved_return.isna()]
    ids=[int(value) for value in pending.permno.unique()]
    if len(ids)>500:raise ValueError('Terminal audit exceeds fixed security bound')
    start=prices.date.min().date();end=prices.date.max().date()
    events=database.raw_sql('SELECT * FROM crsp_q_stock.stkdelists WHERE permno=ANY(%s) AND delistingdt BETWEEN %s AND %s',params=(ids,start,end)) if ids else pd.DataFrame(columns=['permno','deldlydt'])
    distributions=database.raw_sql('SELECT * FROM crsp_q_stock.stkdistributions WHERE permno=ANY(%s) AND disexdt BETWEEN %s AND %s',params=(ids,start,end)) if ids else pd.DataFrame(columns=['permno','disexdt'])
    events.to_parquet(output/'terminal_events_PRIVATE.parquet',index=False)
    distributions.to_parquet(output/'terminal_distributions_PRIVATE.parquet',index=False)
    (output/'input_fingerprints.json').write_text(json.dumps({p.name:sha(p) for p in output.glob('*PRIVATE.parquet')},indent=2))
    predictions=pd.read_parquet(prediction_path)
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')]
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet').sort_values('date')
    full_calendar=pd.DatetimeIndex(market.date);calendar=full_calendar[full_calendar>=predictions.date.min()]
    prices=engine.certified_stale_marks(prices,full_calendar)
    scenarios=[];annual=[];reference={}
    for multiplier in [.5,1.,1.5]:
        mode=f'final-quote-multiplier-{multiplier:g}'
        valuation,audit=terminal_marks(prices,events,distributions,full_calendar,multiplier)
        valuation.to_parquet(output/(mode+'_valuation_PRIVATE.parquet'),index=False)
        audit.to_csv(output/(mode+'_terminal_audit_PRIVATE.csv'),index=False)
        for delay in [0,1,2]:
            prepared=engine.prepare(predictions,valuation,calendar,delay)
            for cost in [0,5,10,20]:
                for borrow in [0,100,300]:
                    row={'mode':mode,'delay':delay,'one_way_bps':cost,'borrow_bps':borrow}
                    try:
                        ledger,rejected=engine.portfolio(predictions,valuation,calendar,cost,borrow,delay,prepared=prepared)
                        attribution=ledger.attrs.pop('security_attribution')
                        if not ledger.one_way_turnover.gt(0).any():raise ValueError('No executable turnover')
                        assert np.allclose(ledger.net,ledger.gross-ledger.borrow-ledger.trading_cost,atol=1e-10)
                        assert ledger.unquoted_traded_notional.abs().max()<1e-9
                        nav=(1+ledger.net).cumprod();peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
                        row.update(status='computed-conditional-settlement',total_net=float(nav.iloc[-1]-1),max_drawdown=float((nav/peak-1).min()),
                            mean_turnover=float(ledger.one_way_turnover.mean()),max_gross=float(ledger.gross_exposure.max()),entry_orders_rejected=rejected)
                        ledger.to_csv(output/f'{mode}_delay{delay}_cost{cost}_borrow{borrow}_PRIVATE.csv',index=False)
                        for year,group in ledger.groupby(ledger.date.dt.year):
                            annual.append({**{key:row[key] for key in ['mode','delay','one_way_bps','borrow_bps']},'year':int(year),'net':float((1+group.net).prod()-1),'buffer_year':bool(year>2025)})
                        if delay==0 and cost==10 and borrow==100:
                            attribution.to_csv(output/(mode+'_attribution_PRIVATE.csv'),index=False)
                            joined=ledger.merge(market,on='date',validate='one_to_one').dropna(subset=['vwretd'])
                            beta=np.linalg.lstsq(np.column_stack([np.ones(len(joined)),joined.vwretd]),joined.net,rcond=None)[0]
                            absolute=attribution.net_initial_capital.abs()
                            reference[mode]={'status':row['status'],'daily_mean_interval':study.paired_interval(ledger.net),'market_beta':float(beta[1]),
                                'top10_absolute_contribution_share':float(absolute.nlargest(10).sum()/absolute.sum()) if absolute.sum() else None}
                    except ValueError as error:
                        if not str(error).startswith(('Unresolved held return','Invalid total return','Equity exhausted','Unliquidated ending positions','No executable turnover')):
                            raise
                        row.update(status='not-estimable',reason=str(error))
                        if delay==0 and cost==10 and borrow==100:reference[mode]={'status':'not-estimable','reason':str(error)}
                    scenarios.append(row)
            print('TERMINAL_SCENARIO_CHECKPOINT',mode,delay,flush=True)
    results=pd.DataFrame(scenarios);assert len(results)==108
    results.to_csv(output/'all_108_scenarios_PRIVATE.csv',index=False)
    pd.DataFrame(annual).to_csv(output/'all_annual_results_PRIVATE.csv',index=False)
    (output/'reference_diagnostics_PRIVATE.json').write_text(json.dumps(reference,indent=2))
    report=['# Private terminal-quote implementation sensitivity','',
        'Actual observations and outputs remain private in WRDS Cloud. This is a retrospective, conditional settlement study, not a recovered observed cash payoff or executable liquidation.','',
        'The original observed-only and certified-stale v3 reference strategies remain unestimable. Final-price (PRCF) delist events are valued only if exact identity/date, last trading price and absence of intervening distributions reconcile. The stale economic claim is locked until the quote date and borrowing continues. No quote authorizes an order. Converting a final quote to cash-equivalent value is an explicit settlement assumption. The price is independently multiplied by 0.5, 1.0 and 1.5 as symmetric operational sensitivity; these are not statistical confidence bounds or observed recoveries.','',
        formatting.table(results),'','## Fixed reference diagnostics','',
        '```json',json.dumps(reference,indent=2),'```','',
        'All 108 grid attempts are retained; no trade is removed because its subsequent return is missing. Any remaining unknown holding value still prevents a complete ledger. Finite ledgers reconcile costs, borrow, security contributions and book equity and cannot execute unquoted orders. Annual 2026 results are the predeclared liquidation buffer, not another confirmation year.','',
        'Read the original [statistical study](../final_report/REPORT_PRIVATE.md), [global source review](../final_report_v3_sources/REPORT_PRIVATE.md), and [past-only overlap sensitivity](../final_report_v3_local/REPORT_PRIVATE.md). Conditional intervals are retrospective and do not account for terminal-value model uncertainty, funding, borrow availability or execution impact. No public commercial-data release is authorized by completing the software.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'terminal-sensitivity-processed','reference_status':{key:value['status'] for key,value in reference.items()},
        'observed_cash_settlement_validated':False,'outputs':{p.name:sha(p) for p in output.iterdir() if p.is_file()}},indent=2))
    print('TERMINAL_SENSITIVITY_COMPLETED',flush=True)
