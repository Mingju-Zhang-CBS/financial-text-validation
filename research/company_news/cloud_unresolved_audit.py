"""Private unresolved-valuation audit; exposes only a software remediation route."""
from pathlib import Path
import importlib.util
import datetime
import hashlib
import json
import numpy as np
import pandas as pd


def capture(engine,predictions,prices,calendar):
    try:
        engine.portfolio(predictions,prices,calendar,10,100,0)
    except ValueError as error:
        if not str(error).startswith('Unresolved held return'):
            raise
        trace=error.__traceback__
        while trace:
            if trace.tb_frame.f_code is engine.portfolio.__code__:
                local=trace.tb_frame.f_locals
                missing=~np.isfinite(local['observed'])&(local['previous']!=0)
                return pd.DataFrame({'date':local['date'],'permno':local['assets'][missing],
                    'held_weight':local['previous'][missing]})
            trace=trace.tb_next
        raise ValueError('Missing original failure frame')
    return None


def execute(study,database,engine,output_name='unresolved_valuation_audit_v3',valuation_path=None):
    output=study.OUT/output_name
    if output.resolve().parent!=study.OUT.resolve():raise ValueError('Audit outside private archive')
    output.mkdir(exist_ok=False)
    predictions=pd.read_parquet(study.OUT/'evaluation'/'predictions_private.parquet')
    predictions=predictions.loc[predictions.horizon.eq(5)&predictions.target_type.eq('adjusted')]
    valuation_path=(study.OUT/'implementation_replay_v3_local'/'certified-stale-valuation_valuation_PRIVATE.parquet') if valuation_path is None else Path(valuation_path)
    prices=pd.read_parquet(valuation_path)
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.loc[market.date.ge(predictions.date.min()),'date'])
    gap=capture(engine,predictions,prices,calendar)
    if gap is None:
        route='no-unresolved-reference-failure'
    else:
        merged=gap.merge(prices,on=['permno','date'],how='left',validate='one_to_one')
        merged.to_csv(output/'unresolved_positions_PRIVATE.csv',index=False)
        flags=set(merged.return_missing_flag.dropna())
        if merged.delisting.eq('Y').any() or flags&{'DM','DG','DP'}:
            route='terminal-return-source-reconstruction'
        elif flags and flags.issubset({'MP','GP'}):
            route='endpoint-valuation-source-reconstruction'
        elif flags&{'NS','NT','RA'}:
            route='historical-listing-continuity-review'
        elif flags&{'MV'}:
            route='corporate-action-value-source-review'
        else:
            route='return-component-consistency-review'
        ids=[int(value) for value in gap.permno.unique()]
        if len(ids)>100:
            raise ValueError('Unresolved-source audit exceeds bounded scope')
        first=gap.date.min().date();start=first-datetime.timedelta(days=365);end=first+datetime.timedelta(days=365)
        for schema in ['crsp_q_stock','crsp_a_stock']:
            events=database.raw_sql('SELECT * FROM '+schema+'.stkdelists WHERE permno=ANY(%s) AND delistingdt BETWEEN %s AND %s',params=(ids,start,end))
            events.to_parquet(output/(schema+'_delisting_events_PRIVATE.parquet'),index=False)
        schema=database.raw_sql("SELECT table_schema,table_name,column_name FROM information_schema.columns WHERE table_schema IN ('crsp_q_stock','crsp_a_stock') AND table_name IN ('stkdlysecuritydata','dsf_v2','dsedelist') ORDER BY table_schema,table_name,ordinal_position")
        schema.to_csv(output/'return_source_schema.csv',index=False)
        for (library,table),group in schema.groupby(['table_schema','table_name']):
            available=set(group.column_name)
            if table in {'dsf_v2','stkdlysecuritydata'} and {'permno','dlycaldt','dlyret'}.issubset(available):
                fields=[name for name in ['permno','dlycaldt','dlyret','dlyretx','dlyreti','dlyprevdt','dlyprc','dlyprevprc','dlyfacprc','dlyorddivamt','dlynonorddivamt','dlydistretflg','dlyretmissflg','dlyretdurflg','dlydelflg'] if name in available]
                rows=database.raw_sql('SELECT '+','.join(fields)+' FROM '+library+'.'+table+' WHERE permno=ANY(%s) AND dlycaldt BETWEEN %s AND %s',params=(ids,first-datetime.timedelta(days=60),first+datetime.timedelta(days=120)))
                rows.to_parquet(output/(library+'_'+table+'_return_components_PRIVATE.parquet'),index=False)
            if table=='dsedelist' and {'permno','dlstdt','dlret'}.issubset(available):
                rows=database.raw_sql('SELECT * FROM '+library+'.dsedelist WHERE permno=ANY(%s) AND dlstdt BETWEEN %s AND %s',params=(ids,start,end))
                rows.to_parquet(output/(library+'_legacy_delisting_PRIVATE.parquet'),index=False)
        related=prices.loc[prices.permno.isin(ids)&prices.date.between(pd.Timestamp(first)-pd.Timedelta(days=60),pd.Timestamp(first)+pd.Timedelta(days=120))]
        related.to_parquet(output/'valuation_context_PRIVATE.parquet',index=False)
    (output/'REPORT_PRIVATE.md').write_text('# Private unresolved valuation audit\n\nSoftware remediation route: '+route+'.\n\nThe original constrained-book failure is reproduced and affected records remain private. Review the raw CIZ components, daily-security source, annual/quarterly delisting events, legacy delisting records and valuation context before admitting a new rule. No unknown return or terminal payoff has been imputed by this audit.\n',encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'unresolved-valuation-source-audit-executed','software_remediation_route':route,
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('UNRESOLVED_VALUATION_AUDIT_COMPLETED',flush=True)
