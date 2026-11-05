"""Session-clock contracts for normalized inputs (not a vendor schema adapter)."""
import numpy as np
import pandas as pd


def map_news(news, links):
    records = news.merge(links, on="entity_id", how="left", validate="many_to_many")
    day = pd.to_datetime(records["published_at"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    valid = day.between(pd.to_datetime(records["valid_from"]), pd.to_datetime(records["valid_to"]))
    mapped = records.loc[valid].copy()
    if mapped.groupby(["article_id", "entity_id", "event_type"])["permno"].nunique().gt(1).any():
        raise ValueError("Ambiguous historical security mapping; quarantine before aggregation")
    return mapped.drop_duplicates(["article_id", "entity_id", "event_type", "permno"])


def aggregate_news(news, sessions):
    required = ["article_id", "entity_id", "permno", "published_at", "vendor_available_at", "sentiment", "novelty", "event_type"]
    if news[required].drop(columns=["sentiment"]).isna().any().any():
        raise ValueError("Missing required news timing/identity/novelty")
    news = news.copy()
    for column in ["published_at", "vendor_available_at"]:
        if news[column].map(lambda value: pd.Timestamp(value).tzinfo is None).any():
            raise ValueError("Explicit timezone required")
    if not news["sentiment"].dropna().between(-1, 1).all() or not news["novelty"].between(0, 1).all():
        raise ValueError("Normalized scores outside contract")
    published = pd.to_datetime(news["published_at"], utc=True)
    vendor = pd.to_datetime(news["vendor_available_at"], utc=True)
    news["available"] = published.where(published >= vendor, vendor)
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).sort_values().unique()
    cutoffs = (calendar.tz_localize("America/New_York") + pd.Timedelta(hours=23, minutes=59, seconds=59)).tz_convert("UTC")
    positions = cutoffs.searchsorted(news["available"], side="left")
    news = news.loc[positions < len(calendar)].copy()
    news["date"] = calendar[positions[positions < len(calendar)]]
    identity = ["article_id", "permno"]
    for column in ["available", "sentiment", "novelty"]:
        if news.groupby(identity)[column].nunique(dropna=False).gt(1).any():
            raise ValueError("Conflicting article/entity records require a reviewed resolution")
    unique = news.sort_values(["available", "article_id"]).drop_duplicates(identity)
    grouped = unique.groupby(["permno", "date"])
    daily = grouped.agg(news_count=("article_id", "size"), sentiment=("sentiment", "mean"),
                        sentiment_observed=("sentiment", "count"), novelty=("novelty", "mean"))
    events = news.drop_duplicates(["article_id", "permno", "event_type"]).groupby(["permno", "date"])["event_type"].agg(lambda values: "|".join(sorted(set(values))))
    return daily.join(events).reset_index()


def select_universe(prices, top_n=1000, minimum_price=5, minimum_dollar_volume=1_000_000):
    prices = prices.sort_values(["permno", "date"]).copy()
    prices["dollar_volume_20"] = prices.groupby("permno")["dollar_volume"].transform(lambda values: values.rolling(20, min_periods=20).mean())
    prices["month"] = prices["date"].dt.to_period("M")
    last_sessions = prices.groupby("month")["date"].max()
    snapshot = prices.loc[prices["date"].eq(prices["month"].map(last_sessions))].copy()
    snapshot = snapshot.loc[snapshot["share_code"].isin([10, 11]) & snapshot["exchange"].isin([1, 2, 3])
                            & snapshot["close"].abs().ge(minimum_price) & snapshot["dollar_volume_20"].ge(minimum_dollar_volume)]
    snapshot = snapshot.sort_values(["month", "market_cap", "permno"], ascending=[True, False, True])
    snapshot = snapshot.groupby("month").head(top_n)
    snapshot["month"] = snapshot["month"] + 1
    return prices.merge(snapshot[["permno", "month"]].assign(eligible=True), on=["permno", "month"], how="left")["eligible"].eq(True).set_axis(prices.index).sort_index()


def build_panel(prices, daily, horizons=(1, 5, 20)):
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["permno", "date"])
    if prices.duplicated(["permno", "date"]).any():
        raise ValueError("Duplicate security-session prices")
    calendar = pd.DatetimeIndex(sorted(prices["date"].unique()))
    for _, firm in prices.groupby("permno"):
        expected = calendar[(calendar >= firm["date"].min()) & (calendar <= firm["date"].max())]
        if not pd.DatetimeIndex(firm["date"]).equals(expected):
            raise ValueError("Interior missing exchange sessions must be resolved, not shifted over")
    prices["eligible"] = select_universe(prices)
    panel = prices.merge(daily, on=["permno", "date"], how="left", validate="one_to_one")
    panel["news_count"] = panel["news_count"].fillna(0)
    panel["has_news"] = panel["news_count"].gt(0).astype(int)
    panel["sentiment_missing"] = (panel["has_news"].eq(1) & panel["sentiment"].isna()).astype(int)
    panel["sentiment"] = panel["sentiment"].fillna(0)
    panel["novelty"] = panel["novelty"].fillna(0)
    panel["event_type"] = panel["event_type"].fillna("no-news")
    panel = panel.sort_values(["permno", "date"]).reset_index(drop=True)
    grouped = panel.groupby("permno", sort=False)
    panel["return_1"] = grouped["total_return"].shift(0)
    for window in [5, 20]:
        panel[f"return_{window}"] = grouped["total_return"].transform(lambda values: (1 + values).rolling(window).apply(np.prod, raw=True) - 1)
    panel["volatility_20"] = grouped["total_return"].transform(lambda values: values.rolling(20).std())
    panel["past_coverage"] = grouped["news_count"].transform(lambda values: values.shift(1).rolling(20, min_periods=20).mean())
    panel["log_cap"] = np.log(panel["market_cap"].where(panel["market_cap"] > 0))
    panel["log_liquidity"] = np.log(panel["dollar_volume"].where(panel["dollar_volume"] > 0))
    panel["sentiment_novelty"] = panel["sentiment"] * panel["novelty"]
    panel["sentiment_coverage"] = panel["sentiment"] * np.log1p(panel["past_coverage"])
    panel["entry_date"] = grouped["date"].shift(-1)
    for horizon in horizons:
        panel[f"end_{horizon}"] = grouped["date"].shift(-(horizon + 1))
        for source, target in [("total_return", "raw"), ("market_return", "market")]:
            panel[f"{target}_{horizon}"] = grouped[source].transform(lambda values: (1 + values).shift(-2).rolling(horizon).apply(np.prod, raw=True).shift(-(horizon - 1)) - 1)
        panel[f"adjusted_{horizon}"] = panel[f"raw_{horizon}"] - panel[f"market_{horizon}"]
    return panel


def split_masks(panel, horizon, splits):
    masks = {}
    for name, (first, last) in splits.items():
        end = pd.Timestamp(last + 1, 1, 1)
        masks[name] = (panel["date"].ge(pd.Timestamp(first, 1, 1)) & panel["date"].lt(end)
                       & panel[f"end_{horizon}"].lt(end) & panel["eligible"])
    return masks
