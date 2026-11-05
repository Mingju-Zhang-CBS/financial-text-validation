"""Audited RPA receipt-clock adapter; historical scoring vintages remain unverified."""
import numpy as np
import pandas as pd
import json


def normalize_rpa_events(records, links, sessions):
    input_rows = len(records)
    required = ["timestamp_utc", "rp_story_id", "rp_entity_id", "rp_story_event_index",
                "event_sentiment_score", "event_similarity_days", "topic", "relevance"]
    records = records[required].copy()
    if records[["timestamp_utc", "rp_story_id", "rp_entity_id", "rp_story_event_index"]].isna().any().any():
        raise ValueError("Missing RPA identity or receipt time")
    for field, minimum, maximum in [("event_sentiment_score", -1, 1), ("event_similarity_days", 0, 365), ("relevance", 0, 100)]:
        records[field] = pd.to_numeric(records[field], errors="raise")
        if not records[field].dropna().between(minimum, maximum).all():
            raise ValueError(f"Invalid RPA {field}")
    records["receipt_at"] = pd.to_datetime(records["timestamp_utc"], utc=True)
    key = ["rp_story_id", "rp_entity_id", "rp_story_event_index"]
    earliest = records.groupby(["rp_story_id", "rp_entity_id"])["receipt_at"].transform("min")
    records = records.loc[records.receipt_at.eq(earliest)].copy()
    for field in ["event_sentiment_score", "event_similarity_days", "topic"]:
        if records.groupby(key)[field].nunique(dropna=False).gt(1).any():
            raise ValueError("Conflicting event scores at first receipt require review")
    records = records.drop_duplicates(key).reset_index(drop=True).copy()
    records["source_row"] = records.index
    records["mapping_day"] = records.receipt_at.dt.tz_localize(None).dt.normalize()
    mapped = records.merge(links, on="rp_entity_id", how="left", validate="many_to_many")
    mapped = mapped.loc[mapped.mapping_day.between(pd.to_datetime(mapped.valid_from), pd.to_datetime(mapped.valid_to))].copy()
    company_counts = mapped.groupby("source_row").permco.nunique()
    ambiguous = company_counts.index[company_counts.gt(1)]
    mapped = mapped.loc[~mapped.source_row.isin(ambiguous)].drop_duplicates(["source_row", "permno"]).copy()
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).sort_values().unique()
    cutoffs = calendar.tz_localize("America/New_York") + pd.Timedelta(hours=23, minutes=59, seconds=59)
    positions = cutoffs.tz_convert("UTC").searchsorted(mapped.receipt_at)
    mapped = mapped.loc[positions < len(calendar)].copy()
    mapped["date"] = calendar[positions[positions < len(calendar)]]
    mapped["novelty"] = np.log1p(mapped.event_similarity_days) / np.log(366)
    mapped["topic"] = mapped.topic.fillna("no-coded-event")
    article_key = ["rp_story_id", "permno", "date"]
    article = mapped.groupby(article_key).agg(sentiment=("event_sentiment_score", "mean"), novelty=("novelty", "mean")).copy()
    topic_counts = mapped.groupby(article_key + ["topic"]).size().rename("count").reset_index()
    topics = topic_counts.sort_values(["count", "topic"], ascending=[False, True]).drop_duplicates(article_key).set_index(article_key)
    article["event_type"] = topics["topic"]
    article["novelty_missing"] = article.novelty.isna().astype(float)
    daily = article.reset_index().groupby(["permno", "date"]).agg(
        news_count=("rp_story_id", "size"), sentiment=("sentiment", "mean"),
        sentiment_observed=("sentiment", "count"), novelty=("novelty", "mean"),
        novelty_missing=("novelty_missing", "mean"))
    all_daily_topics = article.reset_index().groupby(["permno", "date", "event_type"]).size().rename("count").reset_index()
    daily_topics = all_daily_topics.sort_values(["count", "event_type"], ascending=[False, True]).drop_duplicates(["permno", "date"]).set_index(["permno", "date"])
    daily["event_type"] = daily_topics["event_type"]
    daily = daily.reset_index()
    daily["novelty_observed"] = daily.news_count * (1 - daily.novelty_missing)
    if daily.empty:
        daily["event_topic_counts"] = pd.Series(dtype=str)
    else:
        topic_dicts = all_daily_topics.groupby(["permno", "date"]).apply(
            lambda group: json.dumps(dict(zip(group.event_type, group["count"])), sort_keys=True), include_groups=False)
        daily["event_topic_counts"] = pd.MultiIndex.from_frame(daily[["permno", "date"]]).map(topic_dicts)
    audit = {"source_rows": input_rows, "first_receipt_unique_events": len(records), "date_valid_mapped_rows": int(mapped.source_row.nunique()),
             "ambiguous_company_rows_quarantined": len(ambiguous), "article_security_days": len(article),
             "clock": "vendor receipt proxy; original publication and historical scoring revision unverified",
             "same_company_multiple_classes": "retain links; downstream universe must select one class per company"}
    return daily, audit
