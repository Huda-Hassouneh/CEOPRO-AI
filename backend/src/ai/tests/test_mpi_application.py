"""Application delegation and delivery mapping; native behavior stays in Phase 0 tests."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.ai.core.security import TenantContext
from src.ai.mpi import application, data_access, pipeline
from src.ai.routers import mpi


def test_summary_delegates_existing_pipeline_without_extra_transaction(monkeypatch):
    conn = MagicMock()
    expected = {'status': 'UNKNOWN', 'evidence_id': 'e'}
    compute = MagicMock(return_value=expected)
    monkeypatch.setattr(pipeline, 'get_subject_mpi', compute)
    assert application.compute_summary(conn, 'tenant', 'BUSINESS') is expected
    compute.assert_called_once_with(conn, 'tenant', 'BUSINESS', None)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('scope,subject,canonical', [
    ('BUSINESS', None, None), ('BUSINESS', 'tenant', None),
    ('PRODUCT', 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
    ('COMPETITOR', 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
])
def test_history_validates_then_reads_with_lookahead(monkeypatch, scope, subject, canonical):
    conn = MagicMock()
    events = []
    rows = [('e', datetime(2020, 1, 1, tzinfo=timezone.utc), {}, None, 'explanation')]
    validate = MagicMock(side_effect=lambda *args: events.append('validate'))
    read = MagicMock(side_effect=lambda *args: events.append('read') or rows)
    monkeypatch.setattr(data_access, 'validate_subject', validate)
    monkeypatch.setattr(data_access, 'load_history', read)
    assert application.get_history(conn, 'tenant', scope, subject, 2, 3) is rows
    assert events == ['validate', 'read']
    validate.assert_called_once_with(conn, 'tenant', scope, subject)
    read.assert_called_once_with(conn, 'tenant', pipeline.SOURCE_MODULE, scope, canonical, 3, 3)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


def test_history_default_pagination(monkeypatch):
    monkeypatch.setattr(data_access, 'validate_subject', lambda *args: None)
    read = MagicMock(return_value=[])
    monkeypatch.setattr(data_access, 'load_history', read)
    application.get_history(MagicMock(), 'tenant', 'BUSINESS')
    assert read.call_args.args[-2:] == (21, 0)


@pytest.mark.parametrize('operation', ['compute_summary', 'get_history'])
def test_application_preserves_error_identity(monkeypatch, operation):
    error = data_access.SubjectNotFoundError('MPI subject not found.')
    if operation == 'compute_summary':
        monkeypatch.setattr(pipeline, 'get_subject_mpi', MagicMock(side_effect=error))
    else:
        monkeypatch.setattr(data_access, 'validate_subject', MagicMock(side_effect=error))
        read = MagicMock()
        monkeypatch.setattr(data_access, 'load_history', read)
    with pytest.raises(data_access.SubjectNotFoundError) as raised:
        getattr(application, operation)(MagicMock(), 'tenant', 'BUSINESS')
    assert raised.value is error
    if operation == 'get_history':
        read.assert_not_called()


@pytest.mark.parametrize('route,operation', [('mpi_summary', 'compute_summary'), ('mpi_history', 'get_history')])
def test_router_uses_application_and_retains_later_commit(monkeypatch, route, operation):
    conn = MagicMock()
    monkeypatch.setattr(mpi.db, 'app_role_connection', lambda *args: conn)
    expected = {'status': 'UNKNOWN', 'evidence_id': 'e'}
    def delegate(*args):
        conn.commit.assert_not_called()
        return expected if operation == 'compute_summary' else []
    call = MagicMock(side_effect=delegate)
    monkeypatch.setattr(application, operation, call)
    ctx = TenantContext('tenant', 'actor')
    if route == 'mpi_summary':
        assert mpi.mpi_summary('BUSINESS', None, ctx) is expected
        call.assert_called_once_with(conn, 'tenant', 'BUSINESS', None)
    else:
        assert mpi.mpi_history('BUSINESS', None, 2, 3, ctx) == dict(items=[], has_more=False, limit=2, offset=3)
        call.assert_called_once_with(conn, 'tenant', 'BUSINESS', None, 2, 3)
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.parametrize('operation', ['compute_summary', 'get_history'])
@pytest.mark.parametrize('error,status', [
    (data_access.InvalidSubjectType('Unsupported MPI subject type.'), 422),
    (data_access.InvalidSubjectIdentifier('A valid subject identifier is required.'), 422),
    (data_access.SubjectNotFoundError('private diagnostic'), 404),
])
def test_application_errors_keep_router_mapping(monkeypatch, operation, error, status):
    conn = MagicMock()
    monkeypatch.setattr(mpi.db, 'app_role_connection', lambda *args: conn)
    monkeypatch.setattr(application, operation, MagicMock(side_effect=error))
    ctx = TenantContext('tenant', 'actor')
    with pytest.raises(HTTPException) as raised:
        if operation == 'compute_summary':
            mpi.mpi_summary('BUSINESS', None, ctx)
        else:
            mpi.mpi_history('BUSINESS', None, 20, 0, ctx)
    assert raised.value.status_code == status
    assert raised.value.detail == ('MPI subject not found.' if status == 404 else str(error))
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()
