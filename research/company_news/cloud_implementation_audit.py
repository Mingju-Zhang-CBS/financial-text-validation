"""Bounded source check for a failed implementation book; private Cloud only."""
from pathlib import Path
import datetime
import hashlib
import json
import numpy as np
import pandas as pd


def capture_first_gap(fitting, predictions, prices, calendar):
    try:
        fitting.portfolio(predictions,prices,calendar,10,100,0)
    except ValueError as error:
        if not str(error).startswith('Missing held-security return'):
            raise
        trace=error.__traceback__
        while trace is not None:
            if trace.tb_frame.f_code is fitting.portfolio.__code__:
                local=trace.tb_frame.f_locals
                missing=np.isnan(local['observed'])&(local['previous']!=0)
                return pd.DataFrame({'date':local['date'],'permno':local['assets'][missing],
                    'held_weight_before_return':local['previous'][missing]})
            trace=trace.tb_next
        raise ValueError('Failed book trace could not be reconciled with source')
    return None


def execute(study, fitting, database):
    root=study.OUT
    output=root/'implementation_gap_audit';output.mkdir(exist_ok=False)
    predictions=pd.read_parquet(root/'evaluation'/'predictions_private.parquet')
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')]
    prices=pd.concat([pd.read_parquet(root/f'holding_prices_{year}.parquet') for year in range(2021,2026)],ignore_index=True)
    if prices.groupby(['permno','date'])[['total_return','close','delisting']].nunique(dropna=False).gt(1).any().any():
        raise ValueError('Conflicting holding cache vintages')
    prices=prices.drop_duplicates(['permno','date'])
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.loc[market.date.ge(predictions.date.min()),'date'])
    gaps=capture_first_gap(fitting,predictions,prices,calendar)
    if gaps is None:
        classification='failure-not-reproduced'
    else:
        gaps.to_csv(output/'first_missing_held_return_PRIVATE.csv',index=False)
        identifiers=[int(value) for value in gaps.permno.unique()]
        if len(identifiers)>100:
            classification='bounded-query-limit; wider-source-review-required'
        else:
            date=gaps.date.iloc[0].date()
            query='SELECT permno,dlycaldt AS date,dlyret::float8 AS source_return,dlyprc::float8 AS source_close,dlyretmissflg,dlydelflg FROM crsp_q_stock.dsf_v2 WHERE permno=ANY(%s) AND dlycaldt=%s'
            source=database.raw_sql(query,params=(identifiers,date),date_cols=['date'])
            merged=gaps.merge(source,on=['permno','date'],how='left',validate='one_to_one',indicator=True)
            merged.to_csv(output/'source_reconciliation_PRIVATE.csv',index=False)
            if merged._merge.eq('both').all() and merged.source_return.notna().all():
                classification='cache-source-disagreement; correction-review-required'
            elif merged._merge.eq('left_only').any():
                classification='missing-source-row-confirmed; no-return-imputation'
            else:
                classification='missing-source-return-confirmed; no-return-imputation'
    report=['# Private implementation-gap audit','',
        'A fixed reference book is not promoted to a completed P&L result when a held return is missing.',
        f'Software classification: {classification}.',
        'This bounded check reproduces the first failure using the frozen predictions and original portfolio function. It queries only those securities on that session through the authorized read-only database connection. Actual identifiers, weights, source prices and vendor missingness flags remain in the private CSV files.',
        'A missing return is not replaced by zero or a raw price change. Any cache repair needs source reconciliation and a new recorded run; any sample/design change needs a new protocol version. Subsequent failures are not silently removed. The audit does not establish a completed implementation estimate or resolve borrow/execution assumptions.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'bounded-implementation-source-audit-executed','classification':classification,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('IMPLEMENTATION_SOURCE_AUDIT_FINISHED',flush=True)
