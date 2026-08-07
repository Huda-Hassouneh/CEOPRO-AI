from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.ai.mpi import pipeline


@pytest.fixture
def fake_conn():
    return MagicMock()


def _review(review_id: str, label: str, pos: float, neg: float, days_ago: int = 0, method: str = "PUBLIC_API") -> dict:
    return {
        "review_id": review_id,
        "label": label,
        "positive_probability": pos,
        "negative_probability": neg,
        "effective_date": date(2026, 8, 8 - days_ago) if days_ago < 8 else date(2026, 1, 1),
        "collection_method": method,
    }


def test_no_reviews_records_unknown_evidence(fake_conn):
    with patch.object(pipeline.data_access, "load_scored_reviews", return_value=[]), \
         patch.object(pipeline.data_access, "load_country_context", return_value="JO"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        result = pipeline.get_subject_mpi(fake_conn, "tenant-1", "PRODUCT", "product-1", as_of=date(2026, 8, 8))

    assert result == {"status": "UNKNOWN", "evidence_id": "evidence-1"}
    assert mock_evidence.call_args.args[2] == "UNKNOWN"
    assert mock_evidence.call_args.args[8] == "JO"
    fake_conn.commit.assert_called_once()


def test_below_min_sample_size_flags_low_sample_size(fake_conn):
    reviews = [_review("r1", "positive", 0.8, 0.1)]

    with patch.object(pipeline.data_access, "load_scored_reviews", return_value=reviews), \
         patch.object(pipeline.data_access, "load_country_context", return_value=None), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        result = pipeline.get_subject_mpi(fake_conn, "tenant-1", "PRODUCT", "product-1", as_of=date(2026, 8, 8))

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "LOW_SAMPLE_SIZE"
    explanation = mock_evidence.call_args.args[6]
    assert "LOW SAMPLE SIZE" in explanation
    assert mock_evidence.call_args.args[5] == 0.2


def test_sufficient_sample_reports_fact_with_full_breakdown(fake_conn):
    n = pipeline.cold_start.MIN_SAMPLE_SIZE
    reviews = [_review(f"r{i}", "positive", 0.9, 0.05) for i in range(n)]

    with patch.object(pipeline.data_access, "load_scored_reviews", return_value=reviews), \
         patch.object(pipeline.data_access, "load_country_context", return_value="SA"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        result = pipeline.get_subject_mpi(fake_conn, "tenant-1", "COMPETITOR", "competitor-1", as_of=date(2026, 8, 8))

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "OK"
    assert result["mpi"] > 50  # all-positive reviews
    assert mock_evidence.call_args.args[2] == "FACT"
    assert mock_evidence.call_args.args[8] == "SA"
    source_record_ids = mock_evidence.call_args.args[4]
    assert source_record_ids["subject_type"] == "COMPETITOR"
    assert "mpi" in source_record_ids
    assert "weighted_sentiment_score" in source_record_ids
    assert "volume_confidence" in source_record_ids


def test_reviews_missing_effective_date_are_excluded(fake_conn):
    reviews = [_review("r1", "positive", 0.9, 0.05)]
    reviews[0]["effective_date"] = None

    with patch.object(pipeline.data_access, "load_scored_reviews", return_value=reviews), \
         patch.object(pipeline.data_access, "load_country_context", return_value=None), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        result = pipeline.get_subject_mpi(fake_conn, "tenant-1", "BUSINESS", as_of=date(2026, 8, 8))

    # load_scored_reviews returned one row, but it contributes nothing -
    # same path as zero reviews since the one row is filtered out internally
    assert result["status"] == "UNKNOWN"
    assert mock_evidence.call_args.args[2] == "UNKNOWN"


def test_compare_subjects_refuses_when_one_side_has_no_data(fake_conn):
    def fake_load(conn, tenant_id, subject_type, subject_id=None):
        return [] if subject_type == "COMPETITOR" else [_review("r1", "positive", 0.9, 0.05)]

    with patch.object(pipeline.data_access, "load_scored_reviews", side_effect=fake_load):
        comparison = pipeline.compare_subjects(
            fake_conn, "tenant-1", ("BUSINESS", None), ("COMPETITOR", "c1"), as_of=date(2026, 8, 8)
        )

    assert comparison.comparable is False
    assert comparison.difference is None


def test_compare_subjects_returns_difference_when_both_sides_sufficient(fake_conn):
    n = 15

    def fake_load(conn, tenant_id, subject_type, subject_id=None):
        if subject_type == "BUSINESS":
            return [_review(f"a{i}", "positive", 0.9, 0.05) for i in range(n)]
        return [_review(f"b{i}", "negative", 0.05, 0.9) for i in range(n)]

    with patch.object(pipeline.data_access, "load_scored_reviews", side_effect=fake_load):
        comparison = pipeline.compare_subjects(
            fake_conn, "tenant-1", ("BUSINESS", None), ("COMPETITOR", "c1"),
            as_of=date(2026, 8, 8), min_volume_for_comparison=10,
        )

    assert comparison.comparable is True
    assert comparison.difference > 0
