import importlib.util
from pathlib import Path

import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('fit_study',Path(__file__).with_name('cloud_fit_study.py'))
fit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit)


def fixture():
    dates=pd.bdate_range('2025-01-01',periods=10)
    prices=pd.DataFrame([(day,security,0.,10.,'N') for day in dates for security in [1,2]],columns=['date','permno','total_return','close','delisting'])
    predictions=pd.DataFrame({'date':[dates[0]]*2,'permno':[1,2],'B2':[1.,-1.]})
    return dates,prices,predictions


def test_terminal_payoff_becomes_cash_without_fictitious_liquidation():
    dates,prices,predictions=fixture()
    prices=prices.loc[~(prices.permno.eq(1)&prices.date.gt(dates[3]))].copy()
    terminal=prices.permno.eq(1)&prices.date.eq(dates[3])
    prices.loc[terminal,['total_return','close','delisting']]=[-.5,float('nan'),'Y']
    ledger,rejected=fit.portfolio(predictions,prices,dates,0,0,0)
    assert rejected==0
    assert (1+ledger.net).prod()==pytest.approx(.9)
    assert ledger.gross_exposure.iloc[3:6].tolist()==pytest.approx([.2]*3)
    costly,_=fit.portfolio(predictions,prices,dates,10,0,0)
    assert costly.one_way_turnover.iloc[3]<.1


def test_missing_held_return_stops_the_ledger():
    dates,prices,predictions=fixture()
    prices.loc[prices.permno.eq(1)&prices.date.eq(dates[3]),'total_return']=float('nan')
    with pytest.raises(ValueError,match='Missing held-security'):
        fit.portfolio(predictions,prices,dates,0,0,0)


def test_security_attribution_reconciles_compounding_and_costs():
    dates,prices,predictions=fixture()
    prices.loc[prices.permno.eq(1),'total_return']=.01
    prices.loc[prices.permno.eq(2),'total_return']=-.005
    prices['total_return']=prices.total_return.astype('Float64')
    prices['close']=prices.close.astype('Float64')
    ledger,_=fit.portfolio(predictions,prices,dates,10,100,0,attribution=True)
    detail=ledger.attrs['security_attribution']
    assert detail.net_initial_capital.sum()==pytest.approx((1+ledger.net).prod()-1,abs=1e-12)
    assert detail.cost_initial_capital.sum()>0
    assert detail.borrow_initial_capital.sum()>0
