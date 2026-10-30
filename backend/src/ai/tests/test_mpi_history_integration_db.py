import os,json
from uuid import uuid4
import psycopg2,pytest
from fastapi import Depends
from src.ai.routers import mpi
from src.ai.core.entitlements import requires
from src.ai.core import usage
from src.ai.core.security import create_access_token
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.ai.mpi.evidence import insert_evidence_record
from src.ai import db
from src.ai.core.exceptions import register_exception_handlers

@pytest.fixture
def history(setup):
    client,app,ts,us=setup;register_exception_handlers(app);app.include_router(mpi.router,dependencies=[requires(usage.MARKET_INTELLIGENCE)])
    for tenant,actor in zip(ts,us):
        conn=db.app_role_connection(tenant,actor)
        try:
            for _ in range(3):insert_evidence_record(conn,tenant,'UNKNOWN','ai.mpi',{'subject_type':'BUSINESS','subject_id':None,'status':'UNKNOWN','eligible_review_count':0},None,'Synthetic history fixture: no analyzed reviews.',None)
            conn.commit()
        finally:conn.close()
    return client,ts,us

def count(tenant,table):
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tenant,));return q.fetchone()[0]

def test_history_pagination_is_read_only_uncharged_and_uses_existing_evidence(history):
    client,ts,us=history;before={t:count(ts[0],t) for t in ['evidence_records','usage_ledger','tenant_usage_counters']}
    first=client.get('/mpi/history',params={'subject_type':'BUSINESS','limit':2});assert first.status_code==200,first.text;assert len(first.json()['items'])==2 and first.json()['has_more']
    second=client.get('/mpi/history',params={'subject_type':'BUSINESS','subject_id':ts[0],'offset':2});assert second.status_code==200 and len(second.json()['items'])==1
    assert not({x['evidence_id'] for x in first.json()['items']}&{x['evidence_id'] for x in second.json()['items']})
    assert all(item['result']['status']=='UNKNOWN' for item in first.json()['items'])
    assert before=={t:count(ts[0],t) for t in before}

def test_history_subject_and_tenant_boundaries_are_enforced(history):
    client,ts,us=history;a=client.get('/mpi/history',params={'subject_type':'BUSINESS'}).json()['items']
    assert client.get('/mpi/history',params={'subject_type':'BUSINESS','subject_id':ts[1]}).status_code==404
    assert client.get('/mpi/history',params={'subject_type':'PRODUCT','subject_id':str(uuid4())}).status_code==404
    assert client.get('/mpi/history',params={'subject_type':'PRODUCT','subject_id':'invalid'}).status_code==422
    assert client.get('/mpi/history',params={'subject_type':'OTHER'}).status_code==422
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    b=client.get('/mpi/history',params={'subject_type':'BUSINESS'}).json()['items'];assert not({x['evidence_id'] for x in a}&{x['evidence_id'] for x in b})
    client.headers.clear();assert client.get('/mpi/history',params={'subject_type':'BUSINESS'}).status_code==401

def test_history_retains_existing_market_entitlement_requirement(history):
    client,ts,us=history
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",(ts[0],))
    assert client.get('/mpi/history',params={'subject_type':'BUSINESS'}).status_code==402


@pytest.mark.parametrize('review_count', [0, 1, 5])
def test_repeated_summary_appends_history_current_behavior(history, review_count):
    """Real HTTP/restricted SQL; repeated identical GETs are not deduplicated."""
    client, ts, us = history
    from src.ai.tests.test_mpi_integration_db import _insert_scored_review
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as seed:
        for _ in range(review_count):
            _insert_scored_review(seed, ts[0], 'BUSINESS', 'positive', .9, .1)
    before = count(ts[0], 'evidence_records')
    ids = []
    scores = []
    for _ in range(3):
        response = client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == ('OK' if review_count else 'UNKNOWN')
        ids.append(response.json()['evidence_id'])
        scores.append(response.json().get('mpi'))
    assert len(set(ids)) == 3
    assert scores[0] == scores[1] == scores[2]
    assert count(ts[0], 'evidence_records') == before + 3
    first = client.get('/mpi/history', params={'subject_type': 'BUSINESS', 'limit': 2}).json()
    second = client.get('/mpi/history', params={'subject_type': 'BUSINESS', 'limit': 2, 'offset': 2}).json()
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c, c.cursor() as q:
        q.execute("SELECT evidence_id::text, generated_at FROM evidence_records WHERE tenant_id=%s AND source_module='ai.mpi' ORDER BY generated_at DESC,evidence_id DESC", (ts[0],))
        rows = q.fetchall()
    assert [item['evidence_id'] for item in first['items'] + second['items']] == [r[0] for r in rows[:4]]
    assert first['has_more'] and second['has_more']
    assert all(r[1] is not None for r in rows)
    # Timestamp uniqueness is not guaranteed; UUID provides the tie-break.
    assert count(ts[0], 'evidence_records') == before + 3


@pytest.mark.parametrize('role', ['owner', 'admin', 'manager', 'accountant', 'staff'])
def test_member_roles_summary_hidden_write_current_behavior(history, role):
    client, ts, us = history
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c, c.cursor() as q:
        q.execute('UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s AND user_id=%s', (role, ts[0], us[0]))
    before = count(ts[0], 'evidence_records')
    assert client.get('/mpi/summary', params={'subject_type': 'BUSINESS'}).status_code == 200
    assert client.get('/mpi/history', params={'subject_type': 'BUSINESS'}).status_code == 200
    assert count(ts[0], 'evidence_records') == before + 1


@pytest.mark.parametrize('failure', ['none', 'insert', 'later_commit'])
def test_native_commit_boundaries_and_cleanup_current_behavior(history, monkeypatch, failure):
    """A later commit-call failure is injected; the first commit is real SQL.

    This does not simulate an uncertain network outcome during COMMIT.
    """
    from fastapi.testclient import TestClient
    from psycopg2.extensions import TRANSACTION_STATUS_INTRANS
    from src.ai.core import entitlements
    from src.ai.mpi import evidence
    client, ts, us = history
    original_connect = db.app_role_connection
    original_insert = evidence.insert_evidence_record
    traces = []

    class Trace:
        def __init__(self, inner):
            self.inner = inner
            self.commits, self.rollbacks, self.closed = 0, 0, False
            self.statuses = []
        def cursor(self, *a, **kw):
            return self.inner.cursor(*a, **kw)
        def commit(self):
            self.commits += 1
            self.statuses.append(self.inner._raw.get_transaction_status())
            if failure == 'later_commit' and self.commits == 2:
                raise psycopg2.OperationalError('Synthetic later router failure')
            self.inner.commit()
        def rollback(self):
            self.rollbacks += 1
            self.inner.rollback()
        def close(self):
            self.closed = True
            self.inner.close()

    def connect(*a):
        trace = Trace(original_connect(*a))
        traces.append(trace)
        return trace

    # Separate entitlement connections from the MPI transaction under observation.
    monkeypatch.setattr(entitlements, '_plan', lambda *a: {'status': 'active', 'entitlements': {usage.MARKET_INTELLIGENCE}})
    monkeypatch.setattr(db, 'app_role_connection', connect)
    if failure == 'insert':
        def invalid_category(*a):
            args = list(a)
            args[2] = 'NOT_A_VALID_EVIDENCE_CATEGORY'
            return original_insert(*args)
        monkeypatch.setattr(evidence, 'insert_evidence_record', invalid_category)
    before = count(ts[0], 'evidence_records')
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    safe_client.headers.update(client.headers)
    response = safe_client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
    # Principal verification may use its own authority; only MPI opens this factory here.
    trace = traces[-1]
    assert response.status_code == (200 if failure == 'none' else 500)
    if failure != 'none':
        assert response.json() == {'detail': 'Internal server error.'}
    assert trace.closed
    assert trace.rollbacks == (0 if failure == 'none' else 1)
    assert trace.commits == (0 if failure == 'insert' else 2)
    assert trace.statuses == ([] if failure == 'insert' else [TRANSACTION_STATUS_INTRANS] * 2)
    assert count(ts[0], 'evidence_records') == before + (0 if failure == 'insert' else 1)
    monkeypatch.setattr(evidence, 'insert_evidence_record', original_insert)
    monkeypatch.setattr(db, 'app_role_connection', original_connect)
    assert client.get('/mpi/history', params={'subject_type': 'BUSINESS'}).status_code == 200
    other = original_connect(ts[1], us[1])
    try:
        with other.cursor() as q:
            q.execute('SELECT count(*) FROM evidence_records WHERE tenant_id=%s', (ts[0],))
            assert q.fetchone()[0] == 0
        other.commit()
    finally:
        other.close()


def test_real_serialization_commit_failure_rolls_back_evidence_current_behavior(history, monkeypatch):
    """Two restricted serializable transactions form a deterministic SSI cycle.

    Both inserts succeed before the rival commits. The MPI pipeline's actual
    commit then fails in PostgreSQL; no schema changes or server termination.
    """
    from fastapi.testclient import TestClient
    from src.ai.core import entitlements
    from src.ai.mpi import evidence
    client, ts, us = history
    original_connect = db.app_role_connection
    original_insert = evidence.insert_evidence_record
    target = original_connect(ts[0], us[0])
    rival = original_connect(ts[0], us[0])
    errors = []
    original_commit, original_close = target.commit, target.close
    before = count(ts[0], 'evidence_records')
    try:
        for connection in (target, rival):
            connection._raw.rollback()
            connection._raw.set_session(isolation_level='SERIALIZABLE')
            connection._apply_tenant_context()
            with connection.cursor() as q:
                q.execute('SELECT count(*) FROM evidence_records WHERE tenant_id=%s', (ts[0],))
                assert q.fetchone()[0] == before
        rival_id = original_insert(rival, ts[0], 'UNKNOWN', 'ai.mpi',
            {'subject_type': 'BUSINESS', 'subject_id': None, 'status': 'UNKNOWN'},
            None, 'Synthetic serializable rival.', None)

        def insert_then_commit_rival(*a):
            evidence_id = original_insert(*a)
            rival.commit()
            return evidence_id

        def failing_commit():
            try:
                original_commit()
            except psycopg2.errors.SerializationFailure as exc:
                errors.append(exc.pgcode)
                raise

        def close_and_restore_isolation():
            target._raw.rollback()
            target._raw.set_session(isolation_level='READ COMMITTED')
            original_close()

        target.commit = failing_commit
        target.close = close_and_restore_isolation
        monkeypatch.setattr(db, 'app_role_connection', lambda *a: target)
        monkeypatch.setattr(entitlements, '_plan', lambda *a: {'status': 'active', 'entitlements': {usage.MARKET_INTELLIGENCE}})
        monkeypatch.setattr(evidence, 'insert_evidence_record', insert_then_commit_rival)
        safe_client = TestClient(client.app, raise_server_exceptions=False)
        safe_client.headers.update(client.headers)
        response = safe_client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
        assert response.status_code == 500
        assert response.json() == {'detail': 'Internal server error.'}
        assert errors == ['40001']
        assert target._closed
        assert count(ts[0], 'evidence_records') == before + 1
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c, c.cursor() as q:
            q.execute('SELECT evidence_id::text FROM evidence_records WHERE tenant_id=%s AND explanation_text=%s',
                      (ts[0], 'Synthetic serializable rival.'))
            assert q.fetchall() == [(rival_id,)]
        monkeypatch.setattr(db, 'app_role_connection', original_connect)
        assert client.get('/mpi/history', params={'subject_type': 'BUSINESS'}).status_code == 200
    finally:
        if not target._closed:
            close_and_restore_isolation()
        rival._raw.rollback()
        rival._raw.set_session(isolation_level='READ COMMITTED')
        rival.close()


@pytest.mark.parametrize('state,expected,reason', [
    # Current agreed-plan migration includes MPI in Starter despite the old
    # entitlements module docstring claiming otherwise. Do not change policy.
    ('starter', 200, None), ('missing', 402, 'SUBSCRIPTION_INACTIVE'),
    ('trial', 200, None), ('custom_included', 200, None), ('custom_empty', 402, 'NOT_INCLUDED')])
def test_native_plan_states_gate_both_mpi_routes_current_behavior(history, monkeypatch, state, expected, reason):
    from src.ai.core import entitlements
    client, ts, us = history
    monkeypatch.setenv('UNASSIGNED_PLAN_ACCESS', 'none')
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c, c.cursor() as q:
        if state == 'missing':
            q.execute('DELETE FROM tenant_plan_assignments WHERE tenant_id=%s', (ts[0],))
        elif state == 'starter':
            q.execute("UPDATE tenant_plan_assignments SET plan_key='starter' WHERE tenant_id=%s", (ts[0],))
        elif state == 'trial':
            q.execute("UPDATE tenant_plan_assignments SET status='trialing',source='trial' WHERE tenant_id=%s", (ts[0],))
        else:
            included = [usage.MARKET_INTELLIGENCE] if state == 'custom_included' else []
            q.execute("INSERT INTO tenant_custom_contracts(tenant_id,contract_ref,approved_by,reason,included_features) VALUES(%s,'mpi-synthetic','test-only','MPI characterization fixture',%s::jsonb)", (ts[0], json.dumps(included)))
            q.execute("UPDATE tenant_plan_assignments SET plan_key='custom',source='contract' WHERE tenant_id=%s", (ts[0],))
    entitlements.forget(ts[0])
    before = count(ts[0], 'evidence_records')
    for route in ('summary', 'history'):
        response = client.get('/mpi/' + route, params={'subject_type': 'BUSINESS'})
        assert response.status_code == expected, response.text
        if reason:
            assert response.json()['detail']['reason'] == reason
    assert count(ts[0], 'evidence_records') == before + (1 if expected == 200 else 0)
