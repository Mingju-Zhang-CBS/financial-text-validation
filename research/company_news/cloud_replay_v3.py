"""Versioned private replay with explicit quote and missing-return assumptions."""
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


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def execute(study, database, *, output_name='implementation_replay_v3', alternate_path=None, resolved_archive=None):
    diagnosis=load('replay_source_contract','cloud_return_diagnosis.py')
    engine=load('replay_constrained_book','implementation_v3.py')
    reconciliation=load('replay_reconciliation','return_reconciliation.py')
    report_tools=load('replay_report_tools','cloud_finalize.py')
    output=study.OUT/output_name
    if output.resolve().parent!=study.OUT.resolve():
        raise ValueError('Replay output must remain in private study archive')
    output.mkdir(exist_ok=False)
    prediction_path=study.OUT/'evaluation'/'predictions_private.parquet'
    protocol={'id':output_name,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'frozen before replay outcomes','frozen_prediction_sha256':digest(prediction_path),
        'prediction_selection':'original five-session adjusted B2; no refitting or signal reselection',
        'price_source':'current authorized quarterly CIZ snapshot; original v2 caches remain unchanged',
        'modes':['strict-observed-daily','certified-stale-valuation'],
        'scenario_grid':{'delay':[0,1,2],'one_way_bps':[0,5,10,20],'borrow_bps':[0,100,300]},
        'stale_rule':'MP only, no executable quote, exact previous-price date and P1-P9 duration; locked holdings until a quote; complete vendor payoff on recovery',
        'quote_rule':'positive regular-session execution close AND active trading status; no synthetic execution at a valuation-only price',
        'unresolved_rule':'stop scenario; retain failure; no retrospective trade deletion',
        'alternate_input':None if alternate_path is None else {'path':str(alternate_path),'sha256':digest(Path(alternate_path))},
        'resolved_archive':None if resolved_archive is None else str(resolved_archive),
        'resolved_archive_manifest_sha256':None if resolved_archive is None else digest(Path(resolved_archive)/'manifest.json'),
        'code_sha256':{name:digest(Path(__file__).with_name(name)) for name in ['cloud_replay_v3.py','implementation_v3.py','return_reconciliation.py','cloud_return_diagnosis.py']},
        'publication':'actual observations, ledgers, metrics and figures remain private; completion is not a data license or a prospective test'}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    predictions=pd.read_parquet(prediction_path)
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')]
    assets=[int(value) for value in sorted(predictions.permno.unique())]
    if not 1<=len(assets)<=5000:
        raise ValueError('Prespecified security bound exceeded')
    frames=[];input_hashes={}
    if resolved_archive is None:
        for year in range(2020,2027):
            start=max(f'{year}-01-01','2020-12-01');end=min(f'{year}-12-31','2026-02-28')
            frame=diagnosis.extract_ciz_window(database,'crsp_q_stock',assets,start,end)
            if 'execution_close' not in frame:
                raise ValueError('Regular-session execution-close field is unavailable')
            path=output/f'ciz_snapshot_{year}_PRIVATE.parquet'
            frame.to_parquet(path,index=False);input_hashes[path.name]=digest(path)
            frames.append(frame)
            print('V3_METADATA_SOURCE_YEAR_DONE',year,flush=True)
        prices=pd.concat(frames,ignore_index=True).sort_values(['permno','date'])
    else:
        resolved_archive=Path(resolved_archive)
        validated=json.loads((resolved_archive/'manifest.json').read_text())
        if validated['status']!='source-reconciliation-executed; valuation-only':
            raise ValueError('Unverified alternate-source archive')
        original_path=study.OUT/'implementation_replay_v3'/'resolved_source_before_marks_PRIVATE.parquet'
        if digest(original_path)!=validated['base_snapshot_sha256']:
            raise ValueError('Alternate resolution used a different primary snapshot')
        path=resolved_archive/'resolved_valuation_PRIVATE.parquet'
        if digest(path)!=validated['outputs'][path.name]:
            raise ValueError('Resolved valuation file fingerprint mismatch')
        prices=pd.read_parquet(path)
        original=pd.read_parquet(original_path)
        unchanged=[column for column in original.columns if column not in {'resolved_return','return_provenance'}]
        pd.testing.assert_frame_equal(prices[unchanged].reset_index(drop=True),original[unchanged].reset_index(drop=True))
        input_hashes.update(primary_snapshot=digest(original_path),resolved_snapshot=digest(path))
    if prices.duplicated(['permno','date']).any():
        raise ValueError('Duplicate current CIZ security-session')
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet').sort_values('date')
    full_calendar=pd.DatetimeIndex(market.date)
    calendar=full_calendar[full_calendar>=predictions.date.min()]
    # No observed daily return is replaced. Alternate MP segments must pass the
    # immutable overlap and recovery checks before they can affect valuation.
    if alternate_path is None and resolved_archive is None:
        prices['resolved_return']=prices.total_return
        prices['return_provenance']='original-crsp'
    elif alternate_path is not None:
        alternate=pd.read_parquet(alternate_path)
        prices,overlap=reconciliation.accept_daily_candidates(prices,alternate,calendar=full_calendar)
        overlap.to_csv(output/'alternate_overlap_audit_PRIVATE.csv')
    prices.to_parquet(output/'resolved_source_before_marks_PRIVATE.parquet',index=False)
    (output/'source_input_fingerprints.json').write_text(json.dumps({'recorded':'before P&L scenarios','inputs':input_hashes},indent=2))
    classified=reconciliation.classify_rows(prices)
    classified.groupby(['diagnosis','trading_status'],dropna=False).size().rename('source_rows').to_csv(output/'source_diagnosis_counts_PRIVATE.csv')
    del frames,classified
    scenarios=[];annual=[];reference={}
    for mode in protocol['modes']:
        if mode=='certified-stale-valuation':
            valuation=engine.certified_stale_marks(prices,full_calendar)
        else:
            valuation=prices.copy()
            spanning=valuation.return_duration_flag.astype(str).str.fullmatch(r'P[1-9]')
            undecomposed=valuation.return_provenance.eq('original-crsp')
            valuation.loc[spanning&undecomposed,'resolved_return']=np.nan
        valuation.to_parquet(output/(mode+'_valuation_PRIVATE.parquet'),index=False)
        for delay in [0,1,2]:
            prepared=engine.prepare(predictions,valuation,calendar,delay)
            for cost in [0,5,10,20]:
                for borrow in [0,100,300]:
                    row={'mode':mode,'delay':delay,'one_way_bps':cost,'borrow_bps':borrow}
                    try:
                        ledger,rejected=engine.portfolio(predictions,valuation,calendar,cost,borrow,delay,prepared=prepared)
                        attribution=ledger.attrs.pop('security_attribution')
                        if not ledger.one_way_turnover.gt(0).any():
                            raise ValueError('No executable trades; zero P&L is not strategy evidence')
                        ledger.to_csv(output/f'{mode}_delay{delay}_cost{cost}_borrow{borrow}_PRIVATE.csv',index=False)
                        nav=(1+ledger.net).cumprod()
                        row.update(status='computed',total_net=float(nav.iloc[-1]-1),max_drawdown=float((nav/np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]-1).min()),
                            mean_turnover=float(ledger.one_way_turnover.mean()),max_gross=float(ledger.gross_exposure.max()),max_locked_gross=float(ledger.locked_gross_exposure.max()),
                            unquoted_traded_notional=float(ledger.unquoted_traded_notional.abs().sum()),entry_orders_rejected=rejected)
                        if row['unquoted_traded_notional']>1e-9:
                            raise ValueError('Unquoted trades violate protocol')
                        for year,group in ledger.groupby(ledger.date.dt.year):
                            annual.append({**{key:row[key] for key in ['mode','delay','one_way_bps','borrow_bps']},'year':int(year),'net':float((1+group.net).prod()-1),'buffer_year':bool(year>2025)})
                        if delay==0 and cost==10 and borrow==100:
                            attribution.to_csv(output/(mode+'_reference_attribution_PRIVATE.csv'),index=False)
                            absolute=attribution.net_initial_capital.abs()
                            joined=ledger.merge(market,on='date',validate='one_to_one').dropna(subset=['vwretd'])
                            x=np.column_stack([np.ones(len(joined)),joined.vwretd]);coeff=np.linalg.lstsq(x,joined.net,rcond=None)[0]
                            reference[mode]={'status':'computed','mean_net_date_block_interval':study.paired_interval(ledger.net),
                                'mean_net_daily':float(ledger.net.mean()),'market_beta':float(coeff[1]),'intercept_daily':float(coeff[0]),
                                'top10_absolute_contribution_share':float(absolute.nlargest(10).sum()/absolute.sum()) if absolute.sum() else None,
                                'risk_scope':'Market-only descriptive exposure, not factor-adjusted or causal alpha; interval conditional on valuation rules'}
                    except ValueError as error:
                        if not str(error).startswith(('Unresolved held return','Invalid total return','Equity exhausted','Unliquidated ending positions','No executable trades')):
                            raise
                        row.update(status='not-estimable',reason=str(error))
                        if delay==0 and cost==10 and borrow==100:
                            reference[mode]={'status':'not-estimable','reason':str(error)}
                    scenarios.append(row)
            print('V3_SCENARIO_DELAY_DONE',mode,delay,flush=True)
    result=pd.DataFrame(scenarios);result.to_csv(output/'all_72_scenarios_PRIVATE.csv',index=False)
    pd.DataFrame(annual).to_csv(output/'all_annual_results_PRIVATE.csv',index=False)
    (output/'reference_diagnostics_PRIVATE.json').write_text(json.dumps(reference,indent=2))
    assert len(result)==72
    report=['# Private implementation replay — version 3','',
        'Frozen v2 forecasts are replayed; the original failed study is preserved. The source snapshot and source hashes were recorded before these P&L outcomes.','',
        'Two valuation conventions and all 36 cost/borrow/delay scenarios per convention are retained. Missing economic values are never reported as measured zero returns. Stale marks are a declared accounting convention for certified closed gaps; they defer the complete return to recovery, freeze unquoted dollar holdings, delay exits and continue borrowing costs. A missing corporate action, pending delisting, open gap or unreconciled duration still prevents estimation.','',
        report_tools.table(result),'','## Fixed reference diagnostics','',
        '```json',json.dumps(reference,indent=2),'```','',
        'The fixed reference uses no extra delay, 10 bps one-way traded notional and 100 bps annual short borrowing. Security contributions reconcile with book equity. Market beta and an intercept do not establish comprehensive factor neutrality. Zero tradeable turnover is not accepted as a profitable or validated strategy.','',
        'The calendar includes the predeclared 2026 liquidation buffer. Annual 2026 rows are explicitly marked as a buffer year, not another confirmation year. Results are retrospective daily-close research estimates. Borrow availability, impact, funding, intraday execution and stale-value uncertainty are not observed; no tradable-alpha or prospective-validation claim is made.','',
        'Inspect source_diagnosis_counts_PRIVATE.csv, the source windows and any alternate overlap audit. Cross-source repairs require historical security identity and matching total-return semantics. All failed scenarios remain in all_72_scenarios_PRIVATE.csv. Actual results remain in the authorized Cloud environment.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'v3-replay-processed; review estimability and valuation assumptions',
        'reference_status':{mode:value['status'] for mode,value in reference.items()},
        'outputs':{p.name:digest(p) for p in output.iterdir() if p.is_file()}},indent=2))
    print('IMPLEMENTATION_REPLAY_V3_PROCESSED',flush=True)
