import numpy as np
import pandas as pd
import pytest

from financial_text_validation.company_news.__main__ import synthetic_inputs
from financial_text_validation.company_news.experiment import model_for
from financial_text_validation.company_news.panel import aggregate_news, build_panel, map_news, split_masks
from financial_text_validation.company_news.portfolio import backtest


@pytest.fixture(scope="module")
def inputs():
    prices, news = synthetic_inputs()
    prices = prices.loc[prices.permno.lt(3)].copy()
    news = news.loc[news.permno.lt(3)].copy()
    return prices, news


def test_duplicate_event_labels_do_not_multiply_articles(inputs):
    prices, news = inputs
    extra = news.iloc[[0]].assign(event_type="second-label")
    daily = aggregate_news(pd.concat([news, extra, extra]), prices.date.unique())
    original = aggregate_news(news, prices.date.unique())
    pd.testing.assert_frame_equal(daily.drop(columns="event_type"), original.drop(columns="event_type"))


def test_future_news_cannot_change_past_features(inputs):
    prices, news = inputs
    baseline = build_panel(prices, aggregate_news(news, prices.date.unique()))
    modified = news.copy()
    future = pd.to_datetime(modified.published_at, utc=True).dt.year.ge(2021)
    modified.loc[future, "sentiment"] = 1
    changed = build_panel(prices, aggregate_news(modified, prices.date.unique()))
    pd.testing.assert_frame_equal(baseline.loc[baseline.date.lt("2021-01-01")], changed.loc[changed.date.lt("2021-01-01")])


def test_mapping_obeys_validity_and_rejects_ambiguity(inputs):
    _, news = inputs
    sample = news.iloc[[0]].drop(columns="permno")
    links = pd.DataFrame({"entity_id": ["0", "0"], "permno": [1, 2],
                          "valid_from": ["2000-01-01", "2020-01-01"], "valid_to": ["2019-12-31", "2030-01-01"]})
    assert map_news(sample, links).permno.tolist() == [1]
    with pytest.raises(ValueError, match="Ambiguous"):
        map_news(sample, pd.concat([links, links.iloc[[0]].assign(permno=99)]))


def test_vendor_delay_rolls_news_to_later_session(inputs):
    prices, news = inputs
    sample = news.iloc[[0]].copy()
    sample["vendor_available_at"] = "2009-10-03T12:00:00Z"
    result = aggregate_news(sample, prices.date.unique())
    assert result.date.iloc[0] == pd.Timestamp("2009-10-05")


def test_labels_start_after_next_session_close_and_purge(inputs):
    prices, news = inputs
    panel = build_panel(prices, aggregate_news(news, prices.date.unique()))
    firm = panel.loc[panel.permno.eq(0)].reset_index(drop=True)
    assert firm.raw_1.iloc[0] == pytest.approx(firm.total_return.iloc[2])
    assert firm.raw_5.iloc[0] == pytest.approx((1 + firm.total_return.iloc[2:7]).prod() - 1)
    masks = split_masks(panel, 20, {"train": [2010, 2017]})
    assert panel.loc[masks["train"], "end_20"].max() < pd.Timestamp("2018-01-01")
    assert not masks["train"].loc[panel.date.eq("2017-12-29")].any()


def test_missing_interior_session_rejected(inputs):
    prices, news = inputs
    with pytest.raises(ValueError, match="Interior missing"):
        build_panel(prices.drop(prices.index[40]), aggregate_news(news, prices.date.unique()))


def test_scaling_and_event_vocabulary_fit_only_training(inputs):
    prices, news = inputs
    panel = build_panel(prices, aggregate_news(news, prices.date.unique())).dropna()
    train = panel.loc[panel.date.lt("2018-01-01")]
    model = model_for("B2", 1).fit(train, train.adjusted_5)
    before = model.named_steps["features"].named_transformers_["numeric"].named_steps["scale"].mean_.copy()
    future = panel.loc[panel.date.ge("2021-01-01")].copy()
    future["sentiment"] = 1e9
    future["event_type"] = "confirmation-only-event"
    model.predict(future)
    np.testing.assert_array_equal(before, model.named_steps["features"].named_transformers_["numeric"].named_steps["scale"].mean_)
    assert "confirmation-only-event" not in model.named_steps["features"].named_transformers_["event"].categories_[0]


def test_portfolio_entry_exit_and_one_way_cost():
    dates = pd.bdate_range("2024-01-01", periods=10)
    prices = pd.DataFrame([(date, permno, 0.0) for date in dates for permno in [1, 2]], columns=["date", "permno", "total_return"])
    predictions = pd.DataFrame({"date": [dates[0], dates[0]], "permno": [1, 2], "B2": [-1, 1]})
    ledger = backtest(predictions, prices, cost_bps=10)
    assert ledger.gross_exposure.iloc[0] == 0
    assert ledger.gross_exposure.iloc[1:6].tolist() == pytest.approx([.4] * 5)
    assert ledger.gross_exposure.iloc[6] == 0
    np.testing.assert_allclose(ledger.trading_cost, ledger.one_way_turnover * .001, atol=1e-12)
    assert ledger.one_way_turnover.sum() == pytest.approx(.8, abs=.001)
    assert (1 + ledger.net).prod() < 1
