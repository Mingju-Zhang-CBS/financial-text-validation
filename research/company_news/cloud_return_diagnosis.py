"""Read-only, bounded CRSP gap diagnosis. All observations stay in WRDS Cloud."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import re
import numpy as np
import pandas as pd

_spec=importlib.util.spec_from_file_location('gap_capture_v3',Path(__file__).with_name('cloud_implementation_audit.py'))
capture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(capture)

_spec=importlib.util.spec_from_file_location('reconciliation_diagnosis_v3',Path(__file__).with_name('return_reconciliation.py'))
reconciliation=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(reconciliation)


def identifier(value):
    if not re.fullmatch(r'[a-z_][a-z0-9_]*',value):
        raise ValueError('Unsafe database identifier')
    return '"'+value+'"'


def columns(database, schema, table):
    frame=database.raw_sql('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',params=(schema,table))
    return set(frame.column_name)


def extract_ciz_window(database, schema, identifiers, start, end):
    mapping={'permno':'permno','dlycaldt':'date','dlyret':'total_return','dlyprc':'close',
        'dlyretmissflg':'return_missing_flag','dlyretdurflg':'return_duration_flag',
        'dlyprevdt':'previous_price_date','dlydelflg':'delisting','tradingstatusflg':'trading_status'}
    fields=columns(database,schema,'dsf_v2')
    missing=set(mapping)-fields
    if missing:
        raise ValueError('Required CIZ valuation metadata unavailable; no guessed fields')
    expressions=[]
    for source,target in mapping.items():
        expression=identifier(source)
        if source in {'dlyret','dlyprc'}:
            expression+='::float8'
        expressions.append(expression+' AS '+identifier(target))
    for optional in ['dlyprevprc','dlyfacprc','dlyorddivamt','dlynonorddivamt','dlydistretflg','dlyprcflg','dlyclose','dlyvol']:
        if optional in fields:
            expressions.append(identifier(optional)+(' AS execution_close' if optional=='dlyclose' else ''))
    query='SELECT '+','.join(expressions)+' FROM '+identifier(schema)+'.dsf_v2 WHERE permno=ANY(%s) AND dlycaldt BETWEEN %s AND %s ORDER BY permno,dlycaldt'
    return database.raw_sql(query,params=(identifiers,start,end),date_cols=['date','previous_price_date'])


def execute(study, fitting, database):
    output=study.OUT/'daily_return_review_v3';output.mkdir(exist_ok=False)
    protocol={'id':'company-news-return-diagnosis-v3','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'frozen before source-window inspection and v3 replay',
        'source_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'first frozen-reference failure; at most 100 securities; 60 calendar days before and after',
        'source_priority':['CRSP quarterly CIZ','CRSP annual CIZ','legacy CRSP for ordinary non-delisting comparisons through 2024','Compustat daily via date-valid CCM GVKEY/IID'],
        'rules':['No ticker substitution','No unresolved corporate-action or delisting values replaced by zero',
            'Compustat candidates require positive PRCCD/AJEXDI/TRFD, USD currency continuity and adjacent exchange sessions',
            'At least 20 observed ordinary daily-return overlaps; all within atol=1e-6,rtol=1e-5',
            'No double-counting a CRSP multi-session recovery after alternate daily fills',
            'Stale marks are explicit valuation assumptions, with frozen unquoted holdings and full later certified payoff',
            'Do not overwrite v2 forecasts, labels, scenarios, protocols or reports'],
        'public_release':'independent code and invented tests only; actual diagnostics remain private'}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    prediction_path=study.OUT/'evaluation'/'predictions_private.parquet'
    with prediction_path.open('rb') as stream:
        (output/'frozen_prediction_sha256.txt').write_text(hashlib.file_digest(stream,'sha256').hexdigest())
    predictions=pd.read_parquet(prediction_path)
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')]
    prices=pd.concat([pd.read_parquet(study.OUT/f'holding_prices_{year}.parquet') for year in range(2021,2026)],ignore_index=True)
    if prices.groupby(['permno','date'])[['total_return','close','delisting']].nunique(dropna=False).gt(1).any().any():
        raise ValueError('Conflicting original price-cache vintages')
    prices=prices.drop_duplicates(['permno','date'])
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.loc[market.date.ge(predictions.date.min()),'date'])
    gaps=capture.capture_first_gap(fitting,predictions,prices,calendar)
    if gaps is None:
        raise ValueError('Original missing-held-return failure did not reproduce')
    ids=[int(value) for value in gaps.permno.unique()]
    if len(ids)>100:
        raise ValueError('Bounded security limit exceeded')
    start=(gaps.date.min()-pd.Timedelta(days=60)).date()
    end=(gaps.date.max()+pd.Timedelta(days=60)).date()
    windows={};capabilities={}
    for schema in ['crsp_q_stock','crsp_a_stock']:
        available=columns(database,schema,'dsf_v2')
        capabilities[schema+'.dsf_v2']=sorted(available)
        if available:
            window=extract_ciz_window(database,schema,ids,start,end)
            windows[schema]=window
            reconciliation.classify_rows(window).to_parquet(output/(schema+'_window_PRIVATE.parquet'),index=False)
    primary=windows['crsp_q_stock']
    diagnosed=reconciliation.classify_rows(primary)
    gap_diagnosis=gaps.merge(diagnosed,on=['permno','date'],how='left',validate='one_to_one')
    gap_diagnosis.to_csv(output/'first_gap_diagnosis_PRIVATE.csv',index=False)
    tables=database.raw_sql("SELECT table_schema,table_name FROM information_schema.tables WHERE table_name IN ('secd','ccmxpf_lnkhist','dsf','stkdelists','stkdlysecuritydata') AND left(table_schema,4) IN ('comp','crsp') ORDER BY table_schema,table_name")
    tables.to_csv(output/'available_candidate_tables.csv',index=False)
    for row in tables.itertuples(index=False):
        capabilities[row.table_schema+'.'+row.table_name]=sorted(columns(database,row.table_schema,row.table_name))
    # A comparison of legacy RET is diagnostic only: no second DLRET is added
    # to CIZ, and the legacy source cannot silently truncate the 2025 study.
    if 'crsp_a_stock.dsf' in capabilities and {'permno','date','ret'}.issubset(capabilities['crsp_a_stock.dsf']):
        legacy=database.raw_sql('SELECT permno,date,ret::float8 AS legacy_return FROM crsp_a_stock.dsf WHERE permno=ANY(%s) AND date BETWEEN %s AND %s',params=(ids,start,min(end,datetime.date(2024,12,31))),date_cols=['date'])
        legacy.to_parquet(output/'legacy_comparison_PRIVATE.parquet',index=False)
    (output/'source_capabilities.json').write_text(json.dumps(capabilities,indent=2))
    # Discover CCM/secd access and exact fields before any mapping or formula
    # query. Candidate construction is a separate reviewed stage.
    report=['# Private daily-return diagnosis — v3','',
        'The first original failure is reproduced without changing frozen predictions.',
        'See first_gap_diagnosis_PRIVATE.csv for missingness, return-duration, previous-price-date and trading-status fields; source windows and available alternate schemas are preserved.',
        'MP is a missing price; MV an unknown corporate action value; DM/DG/DP concern delisting; GP/NT/RA require additional treatment. P1–P9 represent multi-session payoffs, not ordinary daily returns.',
        'No alternative return is admitted by the diagnosis stage alone. A complete historical identity, daily total-return construction, overlap audit, bridge reconciliation and executable-quote ledger are required before replay.',
        'Actual prices, securities, flags, mappings and numerical findings stay in WRDS Cloud. V2 artifacts remain unchanged.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'bounded-daily-return-diagnosis-executed',
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('DAILY_RETURN_DIAGNOSIS_V3_COMPLETED',flush=True)
