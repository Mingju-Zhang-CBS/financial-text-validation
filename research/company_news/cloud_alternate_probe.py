"""Bounded alternate-source check for the original first gap; private outputs."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('alternate_rules',Path(__file__).with_name('return_reconciliation.py'))
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


def execute(study,database):
    source=study.OUT/'daily_return_review_v3';output=study.OUT/'alternate_source_probe_v3'
    output.mkdir(exist_ok=False)
    protocol={'id':'bounded-alternate-source-probe-v3','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'original first affected securities; existing bounded source window',
        'source_order':['annual-ciz','legacy-crsp','compustat-daily'],
        'gate':'historical identity, adjacent exchange sessions, currency continuity, complete total-return factors, 20 matching daily overlaps with atol1e-6/rtol1e-5; verified multi-session recovery decomposition',
        'quote_scope':'Candidates are valuation comparisons only. Compustat quote-status semantics require separate review; no alternate price is used for execution.',
        'claim':'This probe does not admit an alternate source into the full replay or change frozen forecasts'}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    primary=pd.read_parquet(source/'crsp_q_stock_window_PRIVATE.parquet')
    gaps=pd.read_csv(source/'first_gap_diagnosis_PRIVATE.csv',parse_dates=['date'])
    ids=[int(value) for value in gaps.permno.unique()]
    if len(ids)>100:
        raise ValueError('Bounded source probe exceeds security limit')
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.date)
    candidates={};capabilities=json.loads((source/'source_capabilities.json').read_text())
    annual_path=source/'crsp_a_stock_window_PRIVATE.parquet'
    if annual_path.exists():
        annual=pd.read_parquet(annual_path)
        annual['candidate_return']=annual.total_return.where(annual.return_duration_flag.isin(rules.DAILY_DURATION)&annual.delisting.eq('N'))
        candidates['annual-ciz']=annual[['permno','date','candidate_return']]
    start=primary.date.min().date();end=primary.date.max().date()
    legacy_fields=set(capabilities.get('crsp_a_stock.dsf',[]))
    if {'permno','date','ret','prc'}.issubset(legacy_fields) and start<=datetime.date(2024,12,31):
        legacy=database.raw_sql('SELECT permno,date,ret::float8 AS candidate_return,prc::float8 AS legacy_price FROM crsp_a_stock.dsf WHERE permno=ANY(%s) AND date BETWEEN %s AND %s',params=(ids,start,min(end,datetime.date(2024,12,31))),date_cols=['date'])
        legacy=legacy.sort_values(['permno','date'])
        previous_date=legacy.groupby('permno').date.shift(1)
        previous_price=legacy.groupby('permno').legacy_price.shift(1)
        position=calendar.get_indexer(legacy.date);prior=calendar.get_indexer(previous_date)
        valid=(prior>=0)&(position==prior+1)&legacy.legacy_price.gt(0)&previous_price.gt(0)&legacy.candidate_return.ge(-1)
        legacy['candidate_return']=legacy.candidate_return.where(valid)
        candidates['legacy-crsp']=legacy[['permno','date','candidate_return']]
    required_link={'gvkey','liid','lpermno','linkdt','linkenddt','linktype'}
    required_daily={'gvkey','iid','datadate','prccd','ajexdi','trfd','curcdd','cshtrd','prcstd'}
    can_link=required_link.issubset(capabilities.get('crsp_q_ccm.ccmxpf_lnkhist',[]))
    can_daily=required_daily.issubset(capabilities.get('comp_na_daily_all.secd',[]))
    if can_link and can_daily:
        links=database.raw_sql("SELECT lpermno::bigint AS permno,gvkey,liid AS iid,linkdt AS valid_from,linkenddt AS valid_to FROM crsp_q_ccm.ccmxpf_lnkhist WHERE lpermno=ANY(%s) AND linktype IN ('LC','LU') AND linkdt<=%s AND (linkenddt>=%s OR linkenddt IS NULL)",params=(ids,end,start),date_cols=['valid_from','valid_to'])
        links['valid_from']=links.valid_from.fillna(pd.Timestamp('1900-01-01'))
        links['valid_to']=links.valid_to.fillna(pd.Timestamp('2100-12-31'))
        matched=rules.exact_historical_links(primary[['permno','date']],links)
        links.to_parquet(output/'historical_ccm_links_PRIVATE.parquet',index=False)
        matched.to_parquet(output/'unambiguous_security_dates_PRIVATE.parquet',index=False)
        gvkeys=sorted(matched.gvkey.dropna().unique().tolist())
        if gvkeys:
            daily=database.raw_sql('SELECT gvkey,iid,datadate AS date,prccd::float8 AS prccd,ajexdi::float8 AS ajexdi,trfd::float8 AS trfd,curcdd,cshtrd::float8 AS share_volume,prcstd FROM comp_na_daily_all.secd WHERE gvkey=ANY(%s) AND datadate BETWEEN %s AND %s',params=(gvkeys,start,end),date_cols=['date'])
            daily=rules.compustat_total_returns(daily,calendar)
            previous_volume=daily.groupby(['gvkey','iid']).share_volume.shift(1)
            daily['candidate_return']=daily.candidate_return.where(daily.share_volume.gt(0)&previous_volume.gt(0))
            daily.to_parquet(output/'compustat_total_return_candidates_PRIVATE.parquet',index=False)
            comp=matched.merge(daily,on=['gvkey','iid','date'],how='left',validate='many_to_one')
            candidates['compustat-daily']=comp[['permno','date','candidate_return']]
    summaries=[]
    for name,candidate in candidates.items():
        candidate.to_parquet(output/(name+'_candidates_PRIVATE.parquet'),index=False)
        reconciled,overlap=rules.accept_daily_candidates(primary,candidate,calendar=calendar)
        reconciled.to_parquet(output/(name+'_reconciliation_PRIVATE.parquet'),index=False)
        overlap.to_csv(output/(name+'_overlap_PRIVATE.csv'))
        first=gaps[['permno','date']].merge(reconciled[['permno','date','resolved_return','return_provenance']],on=['permno','date'],how='left',validate='one_to_one')
        first.to_csv(output/(name+'_first_gap_candidate_PRIVATE.csv'),index=False)
        summaries.append({'source':name,'first_gap_rows':len(first),'candidate_values_passing_math_identity_overlap_gate':int(first.resolved_return.notna().sum()),
            'admitted_into_full_replay':False,'additional_review':'Quote provenance and corporate-action semantics remain review requirements; no execution-price replacement'})
    pd.DataFrame(summaries).to_csv(output/'candidate_status_PRIVATE.csv',index=False)
    report=['# Private bounded alternate-source probe','',
        'The original first failure is compared with annual CIZ, legacy CRSP where covered, and Compustat daily through date-valid security-level CCM links. Compustat total-return index is (PRCCD/AJEXDI)*TRFD; missing factors are not set to one. Positive volume and consecutive USD security-days are required.',
        'Identity ambiguity, insufficient/mismatching ordinary-day overlap, non-MP missingness, and unreconciled multi-session payoffs prevent candidate acceptance. Legacy delisting returns are not added again to CIZ. Candidate calculations and all failed gates remain private.',
        'See candidate_status_PRIVATE.csv and each source reconciliation file. A candidate passing algebra and overlap is not automatically a certified daily execution quotation. This probe does not alter the complete v3 replay or certify Compustat PRCSTD semantics.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'bounded-alternate-source-probe-executed; no automatic price substitution',
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('ALTERNATE_SOURCE_PROBE_V3_COMPLETED',flush=True)
