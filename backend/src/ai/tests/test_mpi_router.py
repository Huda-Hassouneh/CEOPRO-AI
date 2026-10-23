from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ai.core.security import TenantContext
from src.ai.routers import mpi


@pytest.mark.parametrize(
    ("subject_type", "subject_id", "expected_status"),
    [
        ("STORE", None, 422),
        ("PRODUCT", "not-a-uuid", 422),
        ("PRODUCT", "00000000-0000-0000-0000-000000000001", 404),
    ],
)
def test_mpi_subject_errors_are_non_disclosing_and_rollback(
    monkeypatch, subject_type, subject_id, expected_status
):
    connection = MagicMock()
    monkeypatch.setattr(mpi.db, "app_role_connection", lambda tenant_id, user_id: connection)

    def fail(*args, **kwargs):
        if expected_status == 422 and subject_type == "STORE":
            raise mpi.mpi_pipeline.data_access.InvalidSubjectType("Unsupported MPI subject type.")
        if expected_status == 422:
            raise mpi.mpi_pipeline.data_access.InvalidSubjectIdentifier("A valid subject identifier is required.")
        raise mpi.mpi_pipeline.data_access.SubjectNotFoundError("MPI subject not found.")

    monkeypatch.setattr(mpi.mpi_pipeline, "get_subject_mpi", fail)
    with pytest.raises(HTTPException) as raised:
        mpi.mpi_summary(subject_type, subject_id, TenantContext("tenant-a", "user-a"))

    assert raised.value.status_code == expected_status
    if expected_status == 404:
        assert raised.value.detail == "MPI subject not found."
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_mpi_route_requires_authentication():
    app = FastAPI()
    app.include_router(mpi.router)
    response = TestClient(app).get("/mpi/summary", params={"subject_type": "BUSINESS"})
    assert response.status_code == 401
