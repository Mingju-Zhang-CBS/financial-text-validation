"""Fixed-priority, historical-identity total-return repairs; never execution quotes."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('source_resolution_rules',Path(__file__).with_name('return_reconciliation.py'))
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


def apply_complete_segments(combined,reconciled,provider):
    """A lower-priority provider cannot partially overwrite another provider's gap."""
    original_labels={'original-crsp','unresolved'}
    for _,group in reconciled.groupby('permno',sort=False):
        indices=group.sort_values('date').index.to_numpy()
        patch=~reconciled.loc[indices,'return_provenance'].isin(original_labels).to_numpy()
        start=0
        while start<len(indices):
            if not patch[start]:
                start+=1;continue
            end=start
            while end<len(indices) and patch[end]:
                end+=1
            selected=indices[start:end]
            if combined.loc[selected,'return_provenance'].isin(original_labels).all():
                combined.loc[selected,'resolved_return']=reconciled.loc[selected,'resolved_return']
                combined.loc[selected,'return_provenance']=provider+':'+reconciled.loc[selected,'return_provenance']
            start=end
    return combined


def execute(study,database):
    output=study.OUT/'source_reconciliation_v3';output.mkdir(exist_ok=False)
    source_path=study.OUT/'implementation_replay_v3'/'resolved_source_before_marks_PRIVATE.parquet'
    with source_path.open('rb') as stream:
        source_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    protocol={'id':'historical-source-reconciliation-v3','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_priority':['annual-ciz','legacy-crsp','compustat-daily'],
        'scope':'Missing MP/MV/GP valuation intervals in frozen primary snapshot; no forecast refit or outcome selection',
        'annual_and_legacy_flags':['MP'],'compustat_flags':['MP','MV','GP'],
        'compustat_rule':'Exact GVKEY/IID link on both return endpoints, positive complete total-return factors, USD, adjacent exchange sessions and positive volume on both dates',
        'overlap':'At least 20 ordinary observed overlaps; no disagreements beyond atol=1e-6/rtol=1e-5',
        'recovery':'Full alternate daily segment must compound to any observed CRSP multi-session recovery; replace that recovery with its daily component exactly once',
        'unchanged':'Raw primary values, economic identity, execution closes, trading flags, universe and predictions remain unchanged',
        'remaining_limits':'Alternative data are valuation assumptions conditional on provider semantics; quote-status semantics not used as an execution permission; unknown delisting and off-exchange identity are not filled',
        'base_snapshot_sha256':source_hash}
    protocol['source_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    primary=pd.read_parquet(source_path).reset_index(drop=True)
    primary['return_provenance']=np.where(primary.total_return.notna(),'original-crsp','unresolved')
    primary['resolved_return']=primary.total_return
    affected=primary.loc[primary.total_return.isna()&primary.return_missing_flag.isin(['MP','MV','GP']),'permno'].unique()
    ids=[int(value) for value in affected]
    if len(ids)>500:
        raise ValueError('Alternate source audit exceeds 500-security bound')
    combined=primary.copy();audits=[]
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.date)
    if ids:
        start=primary.date.min().date();end=primary.date.max().date()
        module_spec=importlib.util.spec_from_file_location('source_window_extractor',Path(__file__).with_name('cloud_return_diagnosis.py'))
        extractor=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(extractor)
        annual=extractor.extract_ciz_window(database,'crsp_a_stock',ids,start,end)
        annual['candidate_return']=annual.total_return.where(annual.return_duration_flag.isin(rules.DAILY_DURATION)&annual.delisting.eq('N'))
        annual.to_parquet(output/'annual_source_PRIVATE.parquet',index=False)
        providers=[('annual-ciz',annual[['permno','date','candidate_return']],{'MP'})]
        if start<=datetime.date(2024,12,31):
            legacy=database.raw_sql('SELECT permno,date,ret::float8 AS candidate_return,prc::float8 AS legacy_price FROM crsp_a_stock.dsf WHERE permno=ANY(%s) AND date BETWEEN %s AND %s',params=(ids,start,min(end,datetime.date(2024,12,31))),date_cols=['date'])
            legacy=legacy.sort_values(['permno','date'])
            previous=legacy.groupby('permno').date.shift(1);previous_price=legacy.groupby('permno').legacy_price.shift(1)
            position=calendar.get_indexer(legacy.date);prior=calendar.get_indexer(previous)
            legacy['candidate_return']=legacy.candidate_return.where((prior>=0)&(position==prior+1)&legacy.legacy_price.gt(0)&previous_price.gt(0)&legacy.candidate_return.ge(-1))
            legacy.to_parquet(output/'legacy_source_PRIVATE.parquet',index=False)
            providers.append(('legacy-crsp',legacy[['permno','date','candidate_return']],{'MP'}))
        links=database.raw_sql("SELECT lpermno::bigint AS permno,gvkey,liid AS iid,linkdt AS valid_from,linkenddt AS valid_to FROM crsp_q_ccm.ccmxpf_lnkhist WHERE lpermno=ANY(%s) AND linktype IN ('LC','LU') AND linkdt<=%s AND (linkenddt>=%s OR linkenddt IS NULL)",params=(ids,end,start),date_cols=['valid_from','valid_to'])
        links.valid_to=links.valid_to.fillna(pd.Timestamp('2100-12-31'))
        keys=primary.loc[primary.permno.isin(ids),['permno','date']]
        matched=rules.exact_historical_links(keys,links)
        matched.to_parquet(output/'historical_security_dates_PRIVATE.parquet',index=False)
        gvkeys=sorted(matched.gvkey.unique().tolist())
        if gvkeys:
            comp=database.raw_sql('SELECT gvkey,iid,datadate AS date,prccd::float8 AS prccd,ajexdi::float8 AS ajexdi,trfd::float8 AS trfd,curcdd,cshtrd::float8 AS share_volume,prcstd FROM comp_na_daily_all.secd WHERE gvkey=ANY(%s) AND datadate BETWEEN %s AND %s',params=(gvkeys,start,end),date_cols=['date'])
            comp=rules.compustat_total_returns(comp,calendar)
            previous_volume=comp.groupby(['gvkey','iid']).share_volume.shift(1)
            comp.candidate_return=comp.candidate_return.where(comp.share_volume.gt(0)&previous_volume.gt(0))
            comp.to_parquet(output/'compustat_source_PRIVATE.parquet',index=False)
            candidate=matched.merge(comp,on=['gvkey','iid','date'],how='left',validate='many_to_one')
            positions=calendar.get_indexer(candidate.date)
            candidate['prior_date']=pd.NaT
            valid=positions>0
            candidate.loc[valid,'prior_date']=calendar[positions[valid]-1]
            prior_identity=matched.rename(columns={'date':'prior_date'})[['permno','prior_date','gvkey','iid']]
            candidate=candidate.merge(prior_identity.assign(prior_link=True),on=['permno','prior_date','gvkey','iid'],how='left',validate='many_to_one')
            candidate.candidate_return=candidate.candidate_return.where(candidate.prior_link.eq(True))
            providers.append(('compustat-daily',candidate[['permno','date','candidate_return']],{'MP','MV','GP'}))
        for provider,candidate,allowed in providers:
            candidate.to_parquet(output/(provider+'_candidates_PRIVATE.parquet'),index=False)
            reconciled,overlap=rules.accept_daily_candidates(primary,candidate,calendar=calendar,allowed_missing_flags=allowed)
            overlap.to_csv(output/(provider+'_overlap_PRIVATE.csv'))
            before=combined.return_provenance.copy()
            combined=apply_complete_segments(combined,reconciled,provider)
            audits.append({'provider':provider,'rows_resolved_or_recovery_decomposed':int(combined.return_provenance.ne(before).sum())})
            print('SOURCE_RESOLUTION_PROVIDER_DONE',provider,flush=True)
    assert combined[['permno','date']].equals(primary[['permno','date']])
    pd.DataFrame(audits).to_csv(output/'provider_audit_PRIVATE.csv',index=False)
    combined.to_parquet(output/'resolved_valuation_PRIVATE.parquet',index=False)
    report=['# Private historical total-return source reconciliation','',
        'Valuation-only repairs use a fixed source hierarchy and complete segments; no raw observed daily CRSP return or execution quote is overwritten. V2 predictions and sample membership remain fixed.',
        'Annual CIZ and legacy CRSP can supply MP comparisons; Compustat may resolve MP/MV/GP using a complete adjusted total-return index and exact security links at both endpoints. Missing factor values are not set to one. Historical identity, positive volume, currency and overlap gates remain mandatory. Off-exchange/new-security/unknown-delisting values are not automatically reconstructed.',
        'Every admitted daily segment and any decomposed CRSP recovery are recorded in resolved_valuation_PRIVATE.parquet. Complete recovery reconstruction is required, and lower-priority providers cannot partially overwrite a higher-priority interval. These are retrospective data repairs, not proof of point-in-time vendor vintages or executable prices.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'source-reconciliation-executed; valuation-only','base_snapshot_sha256':source_hash,
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('FULL_SOURCE_RECONCILIATION_V3_COMPLETED',flush=True)


def reconcile_cached_local(study):
    """Separate sensitivity: exactly 20 preceding valid overlaps within 60 days.

    No best-window search or tolerance fitting. Preserve the stricter global
    comparison and every primary daily value; cache fingerprints must match.
    """
    cached=study.OUT/'source_reconciliation_v3'
    output=study.OUT/'source_reconciliation_v3_local';output.mkdir(exist_ok=False)
    old=json.loads((cached/'manifest.json').read_text())
    base=study.OUT/'implementation_replay_v3'/'resolved_source_before_marks_PRIVATE.parquet'
    with base.open('rb') as stream:
        base_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    if base_hash!=old['base_snapshot_sha256']:
        raise ValueError('Local audit primary snapshot changed')
    protocol={'id':'source-reconciliation-v3-local-prior20','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'reason':'Separate source-QC sensitivity to whole-history cross-provider discrepancies; no prediction or profitability inspection',
        'scope':'For each missing interval, use exactly the latest 20 ordinary observed matching opportunities before that interval, within 60 calendar days; all must pass original fixed tolerances. No future overlap or best-window selection.',
        'thresholds':{'minimum_overlap':20,'maximum_history_calendar_days':60,'atol':1e-6,'rtol':1e-5},
        'unchanged':'Source priority, identity, currency, factor, volume, corporate-action and recovery gates; all raw primary data and execution quotes; original global-gate results retained',
        'source_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'base_snapshot_sha256':base_hash,
        'source_cache_manifest_sha256':hashlib.sha256((cached/'manifest.json').read_bytes()).hexdigest()}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    primary=pd.read_parquet(base).reset_index(drop=True)
    primary['return_provenance']=np.where(primary.total_return.notna(),'original-crsp','unresolved')
    primary['resolved_return']=primary.total_return
    combined=primary.copy();audits=[]
    market=pd.read_parquet(study.ROOT/'ciz_market_calendar_private.parquet')
    calendar=pd.DatetimeIndex(market.date)
    for provider,flags in [('annual-ciz',{'MP'}),('legacy-crsp',{'MP'}),('compustat-daily',{'MP','MV','GP'})]:
        path=cached/(provider+'_candidates_PRIVATE.parquet')
        if not path.exists():
            continue
        with path.open('rb') as stream:
            candidate_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        if candidate_hash!=old['outputs'][path.name]:
            raise ValueError('Cached candidate fingerprint changed')
        candidate=pd.read_parquet(path)
        reconciled,overlap=rules.accept_daily_candidates(primary,candidate,calendar=calendar,
            allowed_missing_flags=flags,overlap_scope='local-prior20')
        overlap.to_csv(output/(provider+'_global_overlap_diagnostic_PRIVATE.csv'))
        before=combined.return_provenance.copy()
        combined=apply_complete_segments(combined,reconciled,provider)
        audits.append({'provider':provider,'candidate_sha256':candidate_hash,
            'rows_resolved_or_recovery_decomposed':int(combined.return_provenance.ne(before).sum())})
        print('LOCAL_SOURCE_QC_PROVIDER_DONE',provider,flush=True)
    combined.to_parquet(output/'resolved_valuation_PRIVATE.parquet',index=False)
    pd.DataFrame(audits).to_csv(output/'provider_audit_PRIVATE.csv',index=False)
    (output/'REPORT_PRIVATE.md').write_text('# Private local source-QC sensitivity\n\nExactly the preceding 20 ordinary observed overlaps within 60 calendar days must match at unchanged tolerances. Whole-history disagreements remain recorded separately. This is retrospective data reconstruction, not a new prospective or original prespecified forecast test. Source priority, historical identity, two-endpoint links, currency, factors, volume and complete recovery gates remain unchanged. No best window or favorable year is selected. All global-gate attempts remain in their original archive.\n',encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'source-reconciliation-executed; valuation-only','base_snapshot_sha256':base_hash,
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('LOCAL_SOURCE_RECONCILIATION_V3_COMPLETED',flush=True)
