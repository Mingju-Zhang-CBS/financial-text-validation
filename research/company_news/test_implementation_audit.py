import importlib.util
from pathlib import Path
import pandas as pd


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_first_gap_is_captured_from_the_original_book_function():
    fitting=load('gap_book','cloud_fit_study.py')
    audit=load('gap_audit','cloud_implementation_audit.py')
    calendar=pd.bdate_range('2025-01-01',periods=10)
    prices=pd.DataFrame([(date,permno,0.,10.,'N') for date in calendar for permno in [1,2]],columns=['date','permno','total_return','close','delisting'])
    predictions=pd.DataFrame({'date':[calendar[0]]*2,'permno':[1,2],'B2':[1.,-1.]})
    assert audit.capture_first_gap(fitting,predictions,prices,calendar) is None
    prices.loc[prices.date.eq(calendar[3])&prices.permno.eq(1),'total_return']=float('nan')
    gap=audit.capture_first_gap(fitting,predictions,prices,calendar)
    assert gap.permno.tolist()==[1]
    assert gap.date.tolist()==[calendar[3]]
    assert gap.held_weight_before_return.iloc[0]>0
