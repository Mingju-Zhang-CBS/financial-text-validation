import pandas as pd
import pytest

from financial_text_validation.company_news.ravenpack import normalize_rpa_events


def fixture():
    records = pd.DataFrame({"timestamp_utc": ["2025-01-03T21:00:00", "2025-01-03T21:00:00"],
        "rp_story_id": ["invented-story", "invented-story"], "rp_entity_id": ["invented-entity"] * 2,
        "rp_story_event_index": [1, 2], "event_sentiment_score": [.8, -.2],
        "event_similarity_days": [365.0, None], "topic": ["earnings", "earnings"], "relevance": [100, 100]})
    links = pd.DataFrame({"rp_entity_id": ["invented-entity"], "permno": [1], "permco": [10],
        "valid_from": ["2020-01-01"], "valid_to": ["2026-01-01"]})
    return records, links, pd.bdate_range("2025-01-02", periods=6)


def test_event_deduplication_and_article_weighting():
    records, links, sessions = fixture()
    daily, _ = normalize_rpa_events(pd.concat([records, records]), links, sessions)
    assert daily.news_count.tolist() == [1]
    assert daily.sentiment.iloc[0] == pytest.approx(.3)
    assert daily.novelty.iloc[0] == 1


def test_missing_novelty_preserved_separately():
    records, links, sessions = fixture()
    records["event_similarity_days"] = None
    daily, _ = normalize_rpa_events(records, links, sessions)
    assert daily.novelty.isna().all()
    assert daily.novelty_missing.tolist() == [1]


def test_later_revision_cannot_replace_first_receipt():
    records, links, sessions = fixture()
    changed = records.copy()
    changed["timestamp_utc"] = "2025-01-06T15:00:00"
    changed["event_sentiment_score"] = -1
    expected, _ = normalize_rpa_events(records, links, sessions)
    actual, _ = normalize_rpa_events(pd.concat([records, changed]), links, sessions)
    pd.testing.assert_frame_equal(actual, expected)


def test_different_companies_are_quarantined():
    records, links, sessions = fixture()
    links = pd.concat([links, links.assign(permno=2, permco=20)])
    daily, audit = normalize_rpa_events(records, links, sessions)
    assert daily.empty
    assert audit["ambiguous_company_rows_quarantined"] == 2


def test_new_event_index_in_later_revision_cannot_create_a_new_article():
    records, links, sessions = fixture()
    revision = records.iloc[[0]].assign(timestamp_utc="2025-01-06T15:00:00", rp_story_event_index=3)
    expected, _ = normalize_rpa_events(records, links, sessions)
    actual, _ = normalize_rpa_events(pd.concat([records, revision]), links, sessions)
    pd.testing.assert_frame_equal(actual, expected)
