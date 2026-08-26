from unittest.mock import MagicMock, patch

import pytest

from src.ai.extraction import pipeline
from src.ai.extraction.regex_patterns import ExtractedEntity


@pytest.fixture
def fake_conn():
    return MagicMock()


def _news(news_id: str, text: str = "Contact us at info@example.com") -> dict:
    return {"news_id": news_id, "body_text": text}


def _mention(mention_id: str, text: str = "Selling for $20 today") -> dict:
    return {"mention_id": mention_id, "mention_text": text}


def test_extract_and_store_news_records_no_pending_rows(fake_conn):
    with patch.object(pipeline.data_access, "load_known_product_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_known_competitor_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_pending_news_records", return_value=[]):
        count = pipeline.extract_and_store_news_records(fake_conn, "tenant-1")

    assert count == 0
    fake_conn.commit.assert_called_once()


def test_extract_and_store_news_records_persists_and_marks_processed(fake_conn):
    records = [_news("n1"), _news("n2")]
    entities = [ExtractedEntity(entity_type="EMAIL", text="info@example.com", start=14, end=31)]

    with patch.object(pipeline.data_access, "load_known_product_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_known_competitor_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_pending_news_records", return_value=records), \
         patch.object(pipeline, "extract_entities", return_value=entities), \
         patch.object(pipeline.evidence, "insert_extracted_entities", return_value=["e1"]) as mock_insert, \
         patch.object(pipeline.data_access, "mark_news_record_status") as mock_mark:
        count = pipeline.extract_and_store_news_records(fake_conn, "tenant-1")

    assert count == 2
    assert mock_insert.call_count == 2
    mock_insert.assert_any_call(fake_conn, "tenant-1", "news_record", "n1", entities)
    mock_mark.assert_any_call(fake_conn, "n1", "Processed")
    mock_mark.assert_any_call(fake_conn, "n2", "Processed")
    fake_conn.commit.assert_called_once()


def test_extract_and_store_news_records_marks_failed_on_extraction_error(fake_conn):
    records = [_news("n1")]

    with patch.object(pipeline.data_access, "load_known_product_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_known_competitor_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_pending_news_records", return_value=records), \
         patch.object(pipeline, "extract_entities", side_effect=RuntimeError("boom")), \
         patch.object(pipeline.data_access, "mark_news_record_status") as mock_mark:
        count = pipeline.extract_and_store_news_records(fake_conn, "tenant-1")

    assert count == 0
    mock_mark.assert_called_once_with(fake_conn, "n1", "Failed")
    fake_conn.commit.assert_called_once()


def test_extract_and_store_social_mentions_persists_and_marks_processed(fake_conn):
    records = [_mention("m1")]
    entities = [ExtractedEntity(entity_type="MONEY", text="$20", start=11, end=14, normalized_value="20 USD")]

    with patch.object(pipeline.data_access, "load_known_product_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_known_competitor_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_pending_social_mentions", return_value=records), \
         patch.object(pipeline, "extract_entities", return_value=entities), \
         patch.object(pipeline.evidence, "insert_extracted_entities", return_value=["e1"]) as mock_insert, \
         patch.object(pipeline.data_access, "mark_social_mention_status") as mock_mark:
        count = pipeline.extract_and_store_social_mentions(fake_conn, "tenant-1")

    assert count == 1
    mock_insert.assert_called_once_with(fake_conn, "tenant-1", "social_mention", "m1", entities)
    mock_mark.assert_called_once_with(fake_conn, "m1", "Processed")
    fake_conn.commit.assert_called_once()


def test_extract_and_store_social_mentions_marks_failed_on_persistence_error(fake_conn):
    records = [_mention("m1")]
    entities = [ExtractedEntity(entity_type="MONEY", text="$20", start=11, end=14)]

    with patch.object(pipeline.data_access, "load_known_product_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_known_competitor_names", return_value=[]), \
         patch.object(pipeline.data_access, "load_pending_social_mentions", return_value=records), \
         patch.object(pipeline, "extract_entities", return_value=entities), \
         patch.object(pipeline.evidence, "insert_extracted_entities", side_effect=RuntimeError("db down")), \
         patch.object(pipeline.data_access, "mark_social_mention_status") as mock_mark:
        count = pipeline.extract_and_store_social_mentions(fake_conn, "tenant-1")

    assert count == 0
    mock_mark.assert_called_once_with(fake_conn, "m1", "Failed")
    fake_conn.commit.assert_called_once()
