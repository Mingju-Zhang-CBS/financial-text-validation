import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('bounded_probe',Path(__file__).with_name('cloud_alternate_probe.py'))
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def test_candidate_probe_preserves_separation_from_full_replay(tmp_path):
    source=tmp_path/'daily_return_review_v3';source.mkdir()
    dates=pd.bdate_range('2025-01-01',periods=30)
    primary=pd.DataFrame({'permno':1,'date':dates,'total_return':.01,'return_missing_flag':'NA',
        'return_duration_flag':'D1','delisting':'N'})
    primary.loc[20,['total_return','return_missing_flag','return_duration_flag']]=[np.nan,'MP','MR']
    primary.to_parquet(source/'crsp_q_stock_window_PRIVATE.parquet',index=False)
    alternate=primary.copy()
    alternate.loc[20,['total_return','return_missing_flag','return_duration_flag']]=[.01,'NA','D1']
    alternate.to_parquet(source/'crsp_a_stock_window_PRIVATE.parquet',index=False)
    pd.DataFrame({'permno':[1],'date':[dates[20]]}).to_csv(source/'first_gap_diagnosis_PRIVATE.csv',index=False)
    (source/'source_capabilities.json').write_text('{}')
    pd.DataFrame({'date':dates,'vwretd':0.}).to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    class Database:
        def raw_sql(self,*args,**kwargs):
            raise AssertionError('Unavailable provider metadata must not trigger observation queries')
    probe.execute(SimpleNamespace(ROOT=tmp_path,OUT=tmp_path),Database())
    result=pd.read_csv(tmp_path/'alternate_source_probe_v3'/'candidate_status_PRIVATE.csv')
    assert result.candidate_values_passing_math_identity_overlap_gate.iloc[0]==1
    assert not result.admitted_into_full_replay.any()
    assert (tmp_path/'alternate_source_probe_v3'/'manifest.json').exists()
