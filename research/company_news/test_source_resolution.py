import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import hashlib
import json
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('atomic_source_resolution',Path(__file__).with_name('cloud_source_resolution.py'))
resolution=importlib.util.module_from_spec(spec);spec.loader.exec_module(resolution)


def test_lower_priority_provider_cannot_overwrite_part_of_a_recovery_segment():
    dates=pd.bdate_range('2025-01-01',periods=4)
    original=pd.DataFrame({'permno':1,'date':dates,'resolved_return':[0.,.1,np.nan,.3],
        'return_provenance':['original-crsp','higher-source:validated','unresolved','original-crsp']})
    proposed=pd.DataFrame({'permno':1,'date':dates,'resolved_return':[0.,.1,.1,.1],
        'return_provenance':['original-crsp']+['validated-alternate-daily-total-return']*3})
    result=resolution.apply_complete_segments(original.copy(),proposed,'lower-source')
    assert pd.isna(result.resolved_return.iloc[2])
    assert result.resolved_return.iloc[3]==.3
    original.loc[1,'return_provenance']='unresolved'
    result=resolution.apply_complete_segments(original.copy(),proposed,'lower-source')
    assert result.resolved_return.iloc[1:].tolist()==[.1,.1,.1]


def test_corporate_action_candidate_requires_explicit_protocol_opt_in():
    dates=pd.bdate_range('2025-01-01',periods=24)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':[.01]*20+[np.nan]+[.01]*3,
        'return_missing_flag':['NA']*20+['MV']+['NA']*3,
        'return_duration_flag':['D1']*20+['MR']+['D1']*3,'delisting':'N'})
    candidate=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01})
    default,_=resolution.rules.accept_daily_candidates(primary,candidate)
    assert pd.isna(default.resolved_return.iloc[20])
    amended,_=resolution.rules.accept_daily_candidates(primary,candidate,allowed_missing_flags={'MP','MV','GP'})
    assert amended.resolved_return.iloc[20]==.01
    assert amended.total_return.iloc[:20].equals(primary.total_return.iloc[:20])


def test_local_sensitivity_reuses_verified_candidates_and_preserves_original(tmp_path):
    dates=pd.bdate_range('2025-01-01',periods=100)
    base_folder=tmp_path/'implementation_replay_v3';base_folder.mkdir()
    cached=tmp_path/'source_reconciliation_v3';cached.mkdir()
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':.01,'return_missing_flag':'NA','return_duration_flag':'D1','delisting':'N'})
    primary.loc[80,['total_return','return_missing_flag','return_duration_flag']]=[np.nan,'MP','MR']
    base=base_folder/'resolved_source_before_marks_PRIVATE.parquet';primary.to_parquet(base,index=False)
    base_hash=hashlib.sha256(base.read_bytes()).hexdigest()
    candidate=pd.DataFrame({'permno':1,'date':dates,'candidate_return':.01});candidate.loc[[0,99],'candidate_return']=.2
    path=cached/'annual-ciz_candidates_PRIVATE.parquet';candidate.to_parquet(path,index=False)
    (cached/'manifest.json').write_text(json.dumps({'base_snapshot_sha256':base_hash,'outputs':{path.name:hashlib.sha256(path.read_bytes()).hexdigest()}}))
    pd.DataFrame({'date':dates,'vwretd':0.}).to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    resolution.reconcile_cached_local(SimpleNamespace(ROOT=tmp_path,OUT=tmp_path))
    result=pd.read_parquet(tmp_path/'source_reconciliation_v3_local'/'resolved_valuation_PRIVATE.parquet')
    assert result.resolved_return.iloc[80]==.01
    assert hashlib.sha256(base.read_bytes()).hexdigest()==base_hash
