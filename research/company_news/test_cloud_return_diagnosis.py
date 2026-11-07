import importlib.util
from pathlib import Path
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('deep_diagnosis',Path(__file__).with_name('cloud_return_diagnosis.py'))
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


def test_source_identifiers_cannot_change_query_structure():
    with pytest.raises(ValueError,match='Unsafe'):
        d.identifier('crsp_q_stock; DROP TABLE prices')


def test_missing_source_metadata_stops_before_querying_observations():
    class Database:
        calls=0
        def raw_sql(self,query,params=None,**kwargs):
            self.calls+=1
            return pd.DataFrame({'column_name':['permno','dlycaldt','dlyret','dlyprc']})
    db=Database()
    with pytest.raises(ValueError,match='metadata unavailable'):
        d.extract_ciz_window(db,'crsp_q_stock',[1],'2025-01-01','2025-01-10')
    assert db.calls==1


def test_security_and_date_filters_are_bound_and_execution_quote_is_distinct():
    class Database:
        calls=[]
        def raw_sql(self,query,params=None,**kwargs):
            self.calls.append((query,params,kwargs))
            if 'information_schema' in query:
                return pd.DataFrame({'column_name':['permno','dlycaldt','dlyret','dlyprc','dlyretmissflg','dlyretdurflg','dlyprevdt','dlydelflg','tradingstatusflg','dlyclose']})
            return pd.DataFrame()
    db=Database()
    d.extract_ciz_window(db,'crsp_q_stock',[12345],'2025-01-01','2025-01-10')
    query,params,options=db.calls[-1]
    assert '12345' not in query
    assert params==([12345],'2025-01-01','2025-01-10')
    assert 'execution_close' in query
    assert 'previous_price_date' in options['date_cols']
