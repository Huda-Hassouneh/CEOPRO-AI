from types import SimpleNamespace

from src.ai.routers.extraction import _ingestion_job_completion


def _summary(**overrides):
    values = {"rows_partial": 0, "rows_failed": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def _promotion(**overrides):
    values = {"rows_skipped_incomplete": 0, "rows_failed": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_clean_import_is_completed():
    assert _ingestion_job_completion(_summary(), _promotion()) == ("COMPLETED", None)


def test_row_level_validation_or_promotion_failures_use_supported_failed_status():
    for summary, promotion in (
        (_summary(rows_partial=1), _promotion()),
        (_summary(rows_failed=1), _promotion()),
        (_summary(), _promotion(rows_skipped_incomplete=1)),
        (_summary(), _promotion(rows_failed=1)),
    ):
        status, error = _ingestion_job_completion(summary, promotion)
        assert status == "FAILED"
        assert "not promoted" in error
