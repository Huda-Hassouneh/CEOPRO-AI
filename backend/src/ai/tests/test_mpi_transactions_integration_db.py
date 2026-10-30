"""Native ownership and uncommitted-write/delivery windows, not uncertain network COMMIT outcomes."""
import sys

import pytest
from fastapi.testclient import TestClient
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from src.ai import db
from src.ai.core import entitlements, usage
from src.ai.mpi import application, evidence
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_mpi_history_integration_db import count, history
from src.ai.tests.test_products_integration_db import seeded_tenants


@pytest.fixture
def traced_requests(history, monkeypatch):
    client, tenants, users = history
    connect = db.app_role_connection
    traces = []
    # Keep entitlement transactions separate from the MPI connection under test.
    monkeypatch.setattr(entitlements, '_plan', lambda *args: {
        'status': 'active', 'entitlements': {usage.MARKET_INTELLIGENCE}})

    def traced_connect(tenant, user):
        conn = connect(tenant, user)
        trace = {'events': [], 'contexts': [], 'closed': False}
        traces.append(trace)
        commit, rollback, close = conn.commit, conn.rollback, conn.close

        def check_context():
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user, current_setting('app.current_tenant_id'), "
                               "current_setting('app.current_user_id')")
                context = cursor.fetchone()
                assert context == ('ceopro_app', tenant, user)
                cursor.execute('SELECT count(*) FROM evidence_records WHERE tenant_id=%s', (tenants[1],))
                assert cursor.fetchone()[0] == 0
                trace['contexts'].append(context)

        def owned_commit():
            trace['events'].append(('commit', sys._getframe(1).f_code.co_name))
            commit()
            check_context()

        def owned_rollback():
            trace['events'].append(('rollback', sys._getframe(1).f_code.co_name))
            rollback()
            check_context()

        def owned_close():
            trace['events'].append(('close', sys._getframe(1).f_code.co_name))
            close()
            assert conn._raw.get_transaction_status() == TRANSACTION_STATUS_IDLE
            trace['closed'] = conn._closed

        conn.commit, conn.rollback, conn.close = owned_commit, owned_rollback, owned_close
        return conn

    monkeypatch.setattr(db, 'app_role_connection', traced_connect)
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    safe_client.headers.update(client.headers)
    return safe_client, tenants, users, traces, connect


def test_native_summary_and_history_have_distinct_transaction_owners(traced_requests):
    client, tenants, _, traces, _ = traced_requests
    before = count(tenants[0], 'evidence_records')
    response = client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
    assert response.status_code == 200, response.text
    assert traces[-1]['events'] == [('commit', 'get_subject_mpi'), ('commit', 'mpi_summary'),
                                    ('close', 'mpi_summary')]
    assert len(traces[-1]['contexts']) == 2 and traces[-1]['closed']
    assert count(tenants[0], 'evidence_records') == before + 1
    assert client.get('/mpi/history', params={'subject_type': 'BUSINESS'}).status_code == 200
    assert traces[-1]['events'] == [('commit', 'mpi_history'), ('close', 'mpi_history')]
    assert len(traces[-1]['contexts']) == 1 and traces[-1]['closed']
    assert count(tenants[0], 'evidence_records') == before + 1


@pytest.mark.parametrize('window', ['after_insert_before_commit', 'delivery_serialization'])
def test_native_failure_windows_and_subsequent_tenant_checkout(traced_requests, monkeypatch, window):
    client, tenants, users, traces, connect = traced_requests
    original_insert = evidence.insert_evidence_record
    original_summary = application.compute_summary
    inserted = []
    before = count(tenants[0], 'evidence_records')

    if window == 'after_insert_before_commit':
        def interrupted_insert(*args):
            inserted.append(original_insert(*args))
            # Same transaction sees the row; a separate observer cannot yet.
            with args[0].cursor() as cursor:
                cursor.execute('SELECT evidence_id::text FROM evidence_records WHERE evidence_id=%s', (inserted[0],))
                assert cursor.fetchone() == (inserted[0],)
            assert count(tenants[0], 'evidence_records') == before
            raise RuntimeError('Synthetic interruption before pipeline commit')
        monkeypatch.setattr(evidence, 'insert_evidence_record', interrupted_insert)
    else:
        class Unserializable:
            __slots__ = ()

        def bad_delivery(*args):
            result = original_summary(*args)
            inserted.append(result['evidence_id'])
            return {'result': result, 'unserializable': Unserializable()}
        monkeypatch.setattr(application, 'compute_summary', bad_delivery)

    response = client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
    assert response.status_code == 500
    assert response.json() == {'detail': 'Internal server error.'}
    trace = traces[-1]
    assert trace['closed'] and len(inserted) == 1
    if window == 'after_insert_before_commit':
        assert trace['events'] == [('rollback', 'mpi_summary'), ('close', 'mpi_summary')]
        assert len(trace['contexts']) == 1
    else:
        assert trace['events'] == [('commit', 'get_subject_mpi'), ('commit', 'mpi_summary'),
                                   ('close', 'mpi_summary')]
        assert len(trace['contexts']) == 2
    assert count(tenants[0], 'evidence_records') == before + (window == 'delivery_serialization')

    # A subsequent restricted checkout for the other tenant remains isolated.
    other = connect(tenants[1], users[1])
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT current_user,current_setting('app.current_tenant_id')")
            assert cursor.fetchone() == ('ceopro_app', tenants[1])
            cursor.execute('SELECT count(*) FROM evidence_records WHERE tenant_id=%s', (tenants[0],))
            assert cursor.fetchone()[0] == 0
        other.rollback()
    finally:
        other.close()
    assert client.get('/mpi/history', params={'subject_type': 'BUSINESS'}).status_code == 200
