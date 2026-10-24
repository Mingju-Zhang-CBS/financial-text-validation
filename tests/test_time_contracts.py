from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pytest

from financial_text_validation.core import (build_panel, contribution, load_data, make_model, metrics,
                                           normalize_text, paired_interval, split_masks, validate_data)
from financial_text_validation.fetch_data import end_of_day, parse_h10, parse_statement

PROTOCOL = json.loads((Path(__file__).parents[1]/'protocol.json').read_text(encoding='utf-8'))


@pytest.fixture
def inputs():
    dates=pd.bdate_range('2009-01-01','2025-03-01')
    rng=np.random.default_rng(17)
    rates=np.exp(np.cumsum(rng.normal(0,.008,len(dates))))
    quotes=[]
    for date,rate in zip(dates,rates):
        release=(date-pd.Timedelta(days=date.weekday()))+pd.Timedelta(days=7)
        quotes.append(dict(observation_date=str(date.date()),rate=rate,release_date=str(release.date()),available_at=end_of_day(release),source_url='https://www.federalreserve.gov/test',raw_sha256='0'*64))
    statements=[]
    for date in pd.date_range('2009-07-01','2024-12-31',freq='45D'):
        text=f'Inflation employment growth financial conditions policy test event {date.date()}'
        statements.append(dict(event_id=str(date.date()),publication_date=str(date.date()),available_at=end_of_day(date),decision_at=end_of_day(date+pd.Timedelta(days=1)),text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_url='https://www.federalreserve.gov/test',raw_sha256='0'*64))
    return pd.DataFrame(statements),pd.DataFrame(quotes)


def test_feature_clock_is_release_not_measurement(inputs):
    s,q=inputs
    panel,_=build_panel(s,q,PROTOCOL)
    event=panel.iloc[0]
    available=q[pd.to_datetime(q.available_at,utc=True)<=event.decision_at]
    assert event.feature_observation_date == pd.Timestamp(available.observation_date.iloc[-1])
    assert event.feature_observation_date < event.publication_date
    assert event.entry_date > event.decision_at.tz_convert('America/New_York').tz_localize(None).normalize()


def test_unreleased_and_future_quote_perturbations_do_not_change_features(inputs):
    s,q=inputs
    original,_=build_panel(s,q,PROTOCOL)
    decision=original.iloc[0].decision_at
    changed=q.copy()
    changed.loc[pd.to_datetime(changed.available_at,utc=True)>decision,'rate']*=1.8
    perturbed,_=build_panel(s,changed,PROTOCOL)
    from financial_text_validation.core import PRICE
    np.testing.assert_allclose(original.iloc[0][PRICE].astype(float),perturbed.iloc[0][PRICE].astype(float))


def test_delayed_price_stress_keeps_targets_fixed(inputs):
    s,q=inputs
    a,_=build_panel(s,q,PROTOCOL)
    b,_=build_panel(s,q,PROTOCOL,price_delay_days=14)
    np.testing.assert_array_equal(a.event_id,b.event_id)
    np.testing.assert_allclose(a.log_return,b.log_return)
    assert (b.feature_available_at<=b.decision_at-pd.Timedelta(days=14)).all()


def test_labels_purge_on_public_availability(inputs):
    s,q=inputs
    panel,_=build_panel(s,q,PROTOCOL)
    masks=split_masks(panel,PROTOCOL)
    assert panel.loc[masks['train'],'label_available_at'].max()<pd.Timestamp('2017-01-01',tz='America/New_York')
    assert panel.loc[masks['validation'],'label_available_at'].max()<pd.Timestamp('2020-01-01',tz='America/New_York')
    row=panel.loc[masks['train']].index[-1]
    panel.loc[row,'label_available_at']=pd.Timestamp('2017-01-02',tz='UTC')
    assert not split_masks(panel,PROTOCOL)['train'][row]


@pytest.mark.parametrize('family',['price_logistic','text_logistic','fusion_logistic'])
def test_training_only_vocabulary_and_numeric_scaling(inputs,family):
    s,q=inputs
    panel,_=build_panel(s,q,PROTOCOL)
    masks=split_masks(panel,PROTOCOL)
    train=panel[masks['train']].copy()
    test=panel[masks['confirmation']].copy()
    test['text']='holdoutonlytoken '*10
    test['return_1']=1e8
    model=make_model(family,1.,PROTOCOL).fit(train,train.target)
    if family!='price_logistic':
        vocab=model['features'].named_transformers_['text'].vocabulary_
        assert 'holdoutonlytoken' not in vocab
    if family!='text_logistic':
        np.testing.assert_allclose(model['features'].named_transformers_['price'].mean_[0],train.return_1.mean())
    before=model['model'].coef_.copy()
    model.predict_proba(test)
    np.testing.assert_array_equal(before,model['model'].coef_)


def test_duplicates_keep_first_without_future_dependent_filter(inputs):
    s,q=inputs
    last=s.iloc[-1].copy()
    last['text']=s.iloc[0].text.upper()+'!!!'
    last['text_sha256']=hashlib.sha256(last['text'].encode()).hexdigest()
    s.iloc[-1]=last
    panel,excluded=build_panel(s,q,PROTOCOL)
    assert s.iloc[0].event_id in set(panel.event_id)
    assert s.iloc[-1].event_id not in set(panel.event_id)
    assert excluded.reason.str.contains('duplicate').any()


@pytest.mark.parametrize('mutation',['naive_clock','same_day_release','target_column','negative_quote','duplicate_quote'])
def test_invalid_input_contracts_fail_closed(inputs,mutation):
    s,q=inputs
    if mutation=='naive_clock':s.loc[0,'available_at']='2009-07-01'
    if mutation=='same_day_release':q.loc[0,'release_date']=q.loc[0,'observation_date']
    if mutation=='target_column':s['target']=1
    if mutation=='negative_quote':q.loc[0,'rate']=-1
    if mutation=='duplicate_quote':q.loc[1,'observation_date']=q.loc[0,'observation_date']
    with pytest.raises(ValueError):validate_data(s,q)


def test_fixed_width_holiday_does_not_shift_later_quotes():
    header='   COUNTRY         UNIT       Dec. 28      Dec. 29      Dec. 30      Dec. 31      Jan. 1'
    row=' *EMU MEMBERS    EURO           1.4392                    1.4316       1.4332'
    raw=('<pre>'+header+'\n'+row+'</pre>').encode()
    rows=parse_h10(raw,'2010-01-04','https://www.federalreserve.gov/releases/h10/20100104/')
    assert [(r['observation_date'],r['rate']) for r in rows]==[('2009-12-28',1.4392),('2009-12-30',1.4316),('2009-12-31',1.4332)]


def test_html_table_year_rollover_and_missing_day():
    raw=b'<table class="statistics"><tr><th>COUNTRY</th><th>CURRENCY</th><th>Dec. 30</th><th>Dec. 31</th><th>Jan. 1</th><th>Jan. 2</th><th>Jan. 3</th></tr><tr><th>*EMU MEMBERS</th><td>EURO</td><td>1.1</td><td>1.2</td><td>ND</td><td>1.3</td><td>1.4</td></tr></table>'
    rows=parse_h10(raw,'2020-01-06','https://www.federalreserve.gov/releases/h10/20200106/')
    assert rows[0]['observation_date']=='2019-12-30'
    assert rows[-1]['observation_date']=='2020-01-03'


def test_parser_excludes_release_metadata_and_voter_names():
    raw=('<div id="article"><div class="heading col-sm-8"><p class="article__time">January 29, 2020</p></div><div class="col-sm-8"><p>'+'Inflation employment growth policy '*30+'Voting for the action were Secret Name.</p></div></div>').encode()
    r=parse_statement(raw,'https://www.federalreserve.gov/newsevents/pressreleases/monetary20200129a.htm')
    assert 'Secret Name' not in r['text'] and 'January' not in r['text']
    with pytest.raises(ValueError):parse_statement(raw,'https://www.federalreserve.gov/newsevents/pressreleases/monetary20200128a.htm')


def test_paired_identical_models_have_zero_interval():
    y=np.array([0,1]*10)
    p=np.linspace(.1,.9,20)
    for kind in ['accuracy','brier','log_loss']:
        result=paired_interval(y,p,p,kind,PROTOCOL)
        assert result['advantage']==result['low']==result['high']==0
    np.testing.assert_allclose(contribution([1,0],[.8,.2],'log_loss'),[-np.log(.8)]*2)


def test_probability_alignment_and_invalid_probabilities():
    with pytest.raises(ValueError):metrics([0,1],[.2])
    with pytest.raises(ValueError):metrics([0,1],[.2,1.2])
    assert metrics([0,1],[.1,.9])['accuracy']==1


def test_leap_day_is_not_parsed_as_invalid_previous_year():
    raw=b'<table class="statistics"><tr><th>COUNTRY</th><th>CURRENCY</th><th>Feb. 27</th><th>Feb. 28</th><th>Feb. 29</th><th>Mar. 1</th><th>Mar. 2</th></tr><tr><th>*EMU MEMBERS</th><td>EURO</td><td>1.1</td><td>1.2</td><td>1.3</td><td>1.3</td><td>1.4</td></tr></table>'
    rows=parse_h10(raw,'2012-03-05','https://www.federalreserve.gov/releases/h10/20120305/')
    assert rows[2]['observation_date']=='2012-02-29'


def test_targets_and_future_metadata_are_not_model_features(inputs):
    s,q=inputs
    panel,_=build_panel(s,q,PROTOCOL)
    masks=split_masks(panel,PROTOCOL)
    train,test=panel[masks['train']],panel[masks['confirmation']].copy()
    model=make_model('fusion_logistic',1.,PROTOCOL).fit(train,train.target)
    expected=model.predict_proba(test)
    test['target']=1-test.target
    test['log_return']=1e6
    test['label_end']=pd.Timestamp('2100-01-01')
    np.testing.assert_allclose(expected,model.predict_proba(test))


def test_frozen_selection_precedes_confirmation_and_no_holdout_fit(inputs,tmp_path,monkeypatch):
    import financial_text_validation.core as core
    from sklearn.pipeline import Pipeline
    s,q=validate_data(*inputs)
    data=tmp_path/'unit-data';data.mkdir()
    (data/'manifest.json').write_text('{}',encoding='utf-8')
    # Synthetic fixtures exercise the controller; no unit-test outputs are published as research.
    monkeypatch.setattr(core,'load_data',lambda path:(s,q,{'files_sha256':{},'protocol_sha256':hashlib.sha256(json.dumps(PROTOCOL,sort_keys=True).encode()).hexdigest()}))
    monkeypatch.setattr(core,'make_figures',lambda *args:None)
    output=tmp_path/'unit-output'
    original_fit,original_predict=Pipeline.fit,Pipeline.predict_proba
    def guarded_fit(self,X,y=None,**kwargs):
        assert X.publication_date.max()<pd.Timestamp('2020-01-01')
        return original_fit(self,X,y,**kwargs)
    def guarded_predict(self,X,**kwargs):
        if X.publication_date.min()>=pd.Timestamp('2020-01-01'):
            freeze=json.loads((output/'freeze.json').read_text(encoding='utf-8'))
            assert not set(freeze['final_fit_ids']) & set(X.event_id)
            assert freeze['best_price_family'] in ['price_logistic','price_hist_gradient']
        return original_predict(self,X,**kwargs)
    monkeypatch.setattr(Pipeline,'fit',guarded_fit)
    monkeypatch.setattr(Pipeline,'predict_proba',guarded_predict)
    protocol=tmp_path/'protocol.json';protocol.write_text(json.dumps(PROTOCOL),encoding='utf-8')
    result=core.run_study(data,protocol,output)
    assert result['partition_events']['confirmation']>10
    with pytest.raises(ValueError):core.run_study(data,protocol,output)
