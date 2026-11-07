import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('full_replay',Path(__file__).with_name('cloud_replay_v3.py'))
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


def test_synthetic_replay_retains_every_scenario_and_freezes_inputs_before_pnl(tmp_path,monkeypatch):
    archive=tmp_path/'private_archive_v2';(archive/'evaluation').mkdir(parents=True)
    dates=pd.bdate_range('2021-01-04',periods=30)
    predictions=pd.DataFrame([(date,asset,score,5,'adjusted') for date in dates[:3] for asset,score in [(1,1.),(2,-1.)]],columns=['date','permno','B2','horizon','target_type'])
    predictions.to_parquet(archive/'evaluation'/'predictions_private.parquet',index=False)
    pd.DataFrame({'date':dates,'vwretd':0.}).to_parquet(tmp_path/'ciz_market_calendar_private.parquet',index=False)
    prices=pd.DataFrame([(date,asset,.001 if asset==1 else -.001,10.,10.,'N','A','NA','D1') for date in dates for asset in [1,2]],columns=['date','permno','total_return','close','execution_close','delisting','trading_status','return_missing_flag','return_duration_flag'])
    prices['previous_price_date']=prices.groupby('permno').date.shift(1)
    class Database:
        def raw_sql(self,query,params=None,**kwargs):
            assert (archive/'implementation_replay_v3'/'protocol.json').exists()
            if 'information_schema' in query:
                return pd.DataFrame({'column_name':['permno','dlycaldt','dlyret','dlyprc','dlyretmissflg','dlyretdurflg','dlyprevdt','dlydelflg','tradingstatusflg','dlyclose']})
            _,start,end=params
            return prices.loc[prices.date.between(start,end)].copy()
    original=driver.load
    def checked_load(name,filename):
        module=original(name,filename)
        if filename=='implementation_v3.py':
            book=module.portfolio
            def checked_book(*args,**kwargs):
                assert (archive/'implementation_replay_v3'/'source_input_fingerprints.json').exists()
                return book(*args,**kwargs)
            module.portfolio=checked_book
        return module
    monkeypatch.setattr(driver,'load',checked_load)
    study=SimpleNamespace(ROOT=tmp_path,OUT=archive,paired_interval=lambda values:[-.01,.01])
    driver.execute(study,Database())
    output=archive/'implementation_replay_v3'
    results=pd.read_csv(output/'all_72_scenarios_PRIVATE.csv')
    assert len(results)==72
    assert results.status.eq('computed').all()
    assert results.unquoted_traded_notional.abs().max()<1e-9
    manifest=json.loads((output/'manifest.json').read_text())
    assert set(manifest['reference_status'].values())=={'computed'}
    report_spec=importlib.util.spec_from_file_location('final_report_v3',Path(__file__).with_name('cloud_finalize_v3.py'))
    report=importlib.util.module_from_spec(report_spec);report_spec.loader.exec_module(report)
    report.execute(study)
    assert (archive/'final_report_v3'/'REPORT_PRIVATE.md').exists()
    final=json.loads((archive/'final_report_v3'/'manifest.json').read_text())
    assert final['all_reference_conventions_estimable']
    assert not final['commercial_data_publication_authorized']
    alternate=archive/'source_reconciliation_v3';alternate.mkdir()
    base=output/'resolved_source_before_marks_PRIVATE.parquet'
    resolved=pd.read_parquet(base)
    path=alternate/'resolved_valuation_PRIVATE.parquet'
    resolved.to_parquet(path,index=False)
    validation={'status':'source-reconciliation-executed; valuation-only','base_snapshot_sha256':driver.digest(base),'outputs':{path.name:driver.digest(path)}}
    (alternate/'manifest.json').write_text(json.dumps(validation))
    driver.execute(study,None,output_name='implementation_replay_v3_sources',resolved_archive=alternate)
    assert (archive/'implementation_replay_v3_sources'/'manifest.json').exists()
    resolved.loc[0,'execution_close']=999.
    resolved.to_parquet(path,index=False)
    validation['outputs'][path.name]=driver.digest(path)
    (alternate/'manifest.json').write_text(json.dumps(validation))
    with pytest.raises(AssertionError):
        driver.execute(study,None,output_name='implementation_replay_v3_bad_snapshot',resolved_archive=alternate)
