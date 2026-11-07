from unittest.mock import MagicMock

from src.ai.marketing import image_generation, image_worker


def test_worker_does_not_retry_nonretryable_image_generation_error(monkeypatch):
    system_conn = MagicMock()
    tenant_conn = MagicMock()
    failed = MagicMock(return_value="FAILED")
    monkeypatch.setattr(image_worker.image_jobs, "claim", lambda *_args: ("job", "tenant", "user"))
    monkeypatch.setattr(
        image_worker.image_jobs, "get_job",
        lambda *_args: {
            "campaign_id": "campaign", "image_format": "SQUARE", "prompt": "prompt",
            "channel": None, "attach": False, "seed": None,
        },
    )
    monkeypatch.setattr(image_worker.data_access, "get_campaign", lambda *_args: {"status": "COMPLETED"})
    monkeypatch.setattr(
        image_worker.image_service, "generate_and_store",
        MagicMock(side_effect=image_generation.HordeKudosUpfront()),
    )
    monkeypatch.setattr(image_worker.image_jobs, "fail", failed)
    monkeypatch.setattr(image_worker, "_keep_alive", lambda *_args: None)

    result = image_worker.run_one(
        "worker", system_connection=lambda: system_conn,
        tenant_connection=lambda *_args: tenant_conn,
    )

    assert result == "FAILED"
    assert failed.call_args.kwargs["retryable"] is False
    system_conn.close.assert_called_once()
    tenant_conn.close.assert_called_once()
