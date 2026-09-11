"""Offline tests for analysis_worker.py::analyze_tenant() - the real
"regenerate structured summaries automatically right after scraping"
wiring, on the same market.analysis.requested trigger sentiment
classification/score refresh already run on. conn/minio_client/every
downstream call is mocked - this verifies orchestration, not a real DB."""
from unittest.mock import MagicMock, patch

from src.market_scraper import analysis_worker


def test_analyze_tenant_runs_all_three_steps_and_returns_their_results():
    fake_conn = MagicMock()
    with patch("src.market_scraper.analysis_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.analysis_worker.classify_and_store_reviews", return_value={"status": "OK", "analyzed_count": 3}) as mock_sentiment, \
         patch("src.market_scraper.analysis_worker.refresh_score_snapshots", return_value=[1, 2]) as mock_scores, \
         patch("src.market_scraper.analysis_worker.minio_client", return_value="fake-minio-client") as mock_minio, \
         patch("src.market_scraper.analysis_worker.regenerate_all_structured_summaries", return_value={"chunks_ingested_for": 4}) as mock_summaries:
        result = analysis_worker.analyze_tenant("tenant-1")

    mock_sentiment.assert_called_once_with(fake_conn, "tenant-1")
    mock_scores.assert_called_once_with(fake_conn, "tenant-1")
    mock_minio.assert_called_once()
    mock_summaries.assert_called_once_with(fake_conn, "fake-minio-client", "tenant-1")
    assert result == {
        "sentiment": {"status": "OK", "analyzed_count": 3},
        "score_count": 2,
        "summaries": {"chunks_ingested_for": 4},
    }
    fake_conn.close.assert_called_once()


def test_analyze_tenant_survives_a_summary_regeneration_failure():
    """The real point: sentiment classification and score refresh already
    succeeded by the time summary regeneration runs - a failure there
    (e.g. MinIO unreachable) must not fail the whole call, or the whole
    message gets retried from scratch by run_forever()'s own handler."""
    fake_conn = MagicMock()
    with patch("src.market_scraper.analysis_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.analysis_worker.classify_and_store_reviews", return_value={"status": "OK", "analyzed_count": 1}), \
         patch("src.market_scraper.analysis_worker.refresh_score_snapshots", return_value=[]), \
         patch("src.market_scraper.analysis_worker.minio_client", side_effect=RuntimeError("MinIO unreachable")):
        result = analysis_worker.analyze_tenant("tenant-1")

    assert result["sentiment"] == {"status": "OK", "analyzed_count": 1}
    assert result["score_count"] == 0
    assert result["summaries"] is None  # failed gracefully, not raised
    fake_conn.close.assert_called_once()  # connection still cleaned up


def test_analyze_tenant_closes_the_connection_even_if_sentiment_classification_raises():
    fake_conn = MagicMock()
    with patch("src.market_scraper.analysis_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.analysis_worker.classify_and_store_reviews", side_effect=RuntimeError("boom")):
        try:
            analysis_worker.analyze_tenant("tenant-1")
        except RuntimeError:
            pass
    fake_conn.close.assert_called_once()
