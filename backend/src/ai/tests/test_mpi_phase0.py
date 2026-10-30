"""Phase 0: current contracts; doubles below do not prove PostgreSQL durability/RLS."""
import json
import os
import subprocess
import sys
from datetime import date
from unittest.mock import MagicMock

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.core import entitlements, usage
from src.ai.core.exceptions import register_exception_handlers
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.mpi import pipeline, scoring
from src.ai.routers import mpi


@pytest.fixture
def harness(monkeypatch):
    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2020, 1, 1)
    monkeypatch.setattr(pipeline, 'date', Clock)
    conn = MagicMock()
    monkeypatch.setattr(mpi.db, 'app_role_connection', lambda *a: conn)
    monkeypatch.setattr(pipeline.data_access, 'validate_subject', lambda *a: None)
    monkeypatch.setattr(pipeline.data_access, 'load_scored_reviews', lambda *a: [])
    monkeypatch.setattr(pipeline.data_access, 'load_country_context', lambda *a: 'JO')
    app = FastAPI()
    app.include_router(mpi.router, dependencies=[entitlements.requires(usage.MARKET_INTELLIGENCE)])
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext('tenant-a', 'user-a')
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False), conn


@pytest.mark.parametrize('scope', ['BUSINESS', 'PRODUCT', 'COMPETITOR'])
@pytest.mark.parametrize('count', [0, 1, 5])
def test_summary_exact_contract_and_evidence_current_behavior(harness, monkeypatch, scope, count):
    client, conn = harness
    monkeypatch.setattr(pipeline.cold_start, 'MIN_SAMPLE_SIZE', 5)
    monkeypatch.setattr(scoring, 'MIN_VOLUME_FOR_FULL_CONFIDENCE', 20)
    reviews = [dict(review_id=str(i), label='positive', positive_probability=.9,
                    negative_probability=.1, effective_date=date(2020, 1, 1),
                    collection_method='PUBLIC_API') for i in range(count)]
    monkeypatch.setattr(pipeline.data_access, 'load_scored_reviews', lambda *a: reviews)
    writer = MagicMock(return_value='evidence-1')
    monkeypatch.setattr(pipeline.evidence, 'insert_evidence_record', writer)
    response = client.get('/mpi/summary', params={'subject_type': scope, 'subject_id': 'subject-a'},
                          headers={'Accept-Language': 'ar'})
    assert response.status_code == 200
    expected = {'status': 'UNKNOWN', 'evidence_id': 'evidence-1'}
    if count:
        expected = dict(status='OK', evidence_id='evidence-1', mpi=50 + 2 * count,
                        sample_size=dict(sufficient=count >= 5, analyzed_count=count,
                                         minimum_required=5, status='OK' if count >= 5 else 'LOW_SAMPLE_SIZE'),
                        weighted_sentiment_score=.8, volume_confidence=count / 20,
                        review_count=count, avg_recency_weight=1.,
                        avg_reliability_weight=1., label_counts=dict(positive=count, neutral=0, negative=0))
    assert response.json() == expected
    assert client.get('/mpi/summary', params={'subject_type': scope, 'subject_id': 'subject-a'},
                      headers={'Accept-Language': 'en'}).json() == expected
    args = writer.call_args.args
    assert args[1:4] == ('tenant-a', 'FACT' if count else 'UNKNOWN', 'ai.mpi')
    payload = args[4]
    assert payload['subject_type'] == scope and payload['subject_id'] == 'subject-a'
    assert payload['eligible_review_count'] == count
    assert args[7:] == (None, 'JO')
    if count:
        assert payload['eligible_review_ids'] == [str(i) for i in range(count)]
        assert payload['eligible_date_range'] == {'from': '2020-01-01', 'through': '2020-01-01'}
        assert args[5] == (.54 if count == 5 else .2)
        assert payload['review_provenance'][0] == dict(review_id='0', source_platform=None,
            source_id=None, collection_method='PUBLIC_API', effective_date='2020-01-01', sentiment_model_version=None)
    else:
        assert payload == dict(subject_type=scope, subject_id='subject-a', status='UNKNOWN',
                               review_ids=[], eligible_review_count=0)
        assert args[5] is None
        assert args[6] == f'No analyzed reviews are available yet for this {scope.lower()}.'
    assert conn.commit.call_count == 4
    conn.rollback.assert_not_called()
    assert conn.close.call_count == 2


@pytest.mark.parametrize('failure', ['insert', 'pipeline_commit', 'router_commit'])
def test_summary_failure_windows_current_behavior(harness, monkeypatch, failure):
    client, conn = harness
    events = []
    def insert(*args):
        events.append('insert')
        if failure == 'insert':
            raise psycopg2.IntegrityError('synthetic insert failure')
        return 'evidence-1'
    def commit():
        events.append('commit')
        if events.count('commit') == (2 if failure == 'router_commit' else 1):
            raise psycopg2.OperationalError('synthetic commit failure')
    monkeypatch.setattr(pipeline.evidence, 'insert_evidence_record', insert)
    conn.commit.side_effect = commit
    conn.rollback.side_effect = lambda: events.append('rollback')
    conn.close.side_effect = lambda: events.append('close')
    response = client.get('/mpi/summary', params={'subject_type': 'BUSINESS'})
    assert response.status_code == 500
    assert response.json() == {'detail': 'Internal server error.'}
    assert events == ['insert'] + ([] if failure == 'insert' else ['commit'] * (2 if failure == 'router_commit' else 1)) + ['rollback', 'close']
    # This asserts delivery/cleanup only, not durability or real connection reuse.


@pytest.mark.parametrize('status,features,reason', [
    ('active', set(), 'NOT_INCLUDED'), ('cancelled', {usage.MARKET_INTELLIGENCE}, 'SUBSCRIPTION_INACTIVE')])
@pytest.mark.parametrize('route', ['summary', 'history'])
def test_entitlement_denial_prevents_mpi_connection_current_behavior(harness, monkeypatch, status, features, reason, route):
    client, conn = harness
    monkeypatch.setattr(entitlements, '_plan', lambda *a: dict(status=status, entitlements=features))
    opened = MagicMock(return_value=conn)
    monkeypatch.setattr(mpi.db, 'app_role_connection', opened)
    response = client.get('/mpi/' + route, params={'subject_type': 'BUSINESS'})
    assert response.status_code == 402
    assert response.json()['detail']['reason'] == reason
    opened.assert_not_called()


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 101}, {'offset': -1}])
def test_history_pagination_validation_current_behavior(harness, params):
    client, conn = harness
    response = client.get('/mpi/history', params={'subject_type': 'BUSINESS', **params})
    assert response.status_code == 422
    conn.commit.assert_not_called()


def test_pipeline_default_python_day_controls_decay_current_behavior(harness, monkeypatch):
    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2020, 1, 2)
    monkeypatch.setattr(pipeline, 'date', Clock)
    monkeypatch.setattr(pipeline.data_access, 'load_scored_reviews', lambda *a: [dict(
        review_id='r', label='positive', positive_probability=1., negative_probability=0.,
        effective_date=date(2020, 1, 1), collection_method='PUBLIC_API')])
    monkeypatch.setattr(pipeline.evidence, 'insert_evidence_record', lambda *a: 'e')
    result = pipeline.get_subject_mpi(harness[1], 'tenant-a', 'BUSINESS')
    assert result['avg_recency_weight'] == round(.5 ** (1 / scoring.RECENCY_HALF_LIFE_DAYS), 4)
    # An explicit earlier as_of clamps future dates to full recency, independently of SQL eligibility.
    assert pipeline.get_subject_mpi(harness[1], 'tenant-a', 'BUSINESS', as_of=date(2019, 12, 31))['avg_recency_weight'] == 1.


def test_import_time_configuration_capture_in_isolated_process_current_behavior():
    code = '''
import os, importlib, json
from src.ai.mpi import scoring as s, cold_start as c
initial = [s.RECENCY_HALF_LIFE_DAYS, s.MIN_VOLUME_FOR_FULL_CONFIDENCE, c.MIN_SAMPLE_SIZE]
os.environ.update(MPI_RECENCY_HALF_LIFE_DAYS='12', MPI_MIN_VOLUME_FOR_FULL_CONFIDENCE='8', MPI_MIN_SAMPLE_SIZE='3')
captured = [s.RECENCY_HALF_LIFE_DAYS, s.MIN_VOLUME_FOR_FULL_CONFIDENCE, c.MIN_SAMPLE_SIZE]
importlib.reload(s); importlib.reload(c)
print(json.dumps([initial, captured, [s.RECENCY_HALF_LIFE_DAYS, s.MIN_VOLUME_FOR_FULL_CONFIDENCE, c.MIN_SAMPLE_SIZE]]))
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith('MPI_')}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [[90, 20, 5], [90, 20, 5], [12, 8, 3]]


def test_exact_mixed_scoring_vector_current_behavior(monkeypatch):
    monkeypatch.setattr(scoring, 'MIN_VOLUME_FOR_FULL_CONFIDENCE', 20)
    result = scoring.compute_mpi([scoring.ReviewContribution('a', .8, 1., 1., 1.),
                                  scoring.ReviewContribution('b', -.6, .5, .6, 1.)], {'positive': 1, 'negative': 1})
    assert result.as_dict() == dict(mpi=52.38, weighted_sentiment_score=.4769, volume_confidence=.1,
        review_count=2, avg_recency_weight=.75, avg_reliability_weight=.8, label_counts={'positive': 1, 'negative': 1})


@pytest.mark.parametrize('status', ['active', 'trialing'])
def test_access_granting_entitlement_summary_current_behavior(harness, monkeypatch, status):
    client, conn = harness
    monkeypatch.setattr(entitlements, '_plan', lambda *a: dict(status=status, entitlements={usage.MARKET_INTELLIGENCE}))
    monkeypatch.setattr(pipeline.evidence, 'insert_evidence_record', lambda *a: 'e')
    assert client.get('/mpi/summary', params={'subject_type': 'BUSINESS'}).status_code == 200


@pytest.mark.parametrize('failure', [False, True])
def test_history_contract_and_cleanup_current_behavior(harness, monkeypatch, failure):
    from datetime import datetime, timezone
    client, conn = harness
    cursor = conn.cursor.return_value.__enter__.return_value
    timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    payload = dict(subject_type='BUSINESS', subject_id=None, status='UNKNOWN')
    cursor.fetchall.return_value = [('e1', timestamp, payload, None, 'English explanation'),
                                    ('e2', timestamp, {'status': 'OK', 'mpi': 52.}, .2, 'LOW SAMPLE SIZE')]
    if failure:
        cursor.execute.side_effect = psycopg2.OperationalError('synthetic read failure')
    writer = MagicMock()
    monkeypatch.setattr(pipeline.evidence, 'insert_evidence_record', writer)
    response = client.get('/mpi/history', params={'subject_type': 'BUSINESS', 'limit': 1})
    if failure:
        assert response.status_code == 500
        assert response.json() == {'detail': 'Internal server error.'}
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
    else:
        assert response.status_code == 200
        assert response.json() == dict(items=[dict(evidence_id='e1', generated_at=timestamp.isoformat(),
            result=payload, confidence_score=None, explanation='English explanation')], has_more=True, limit=1, offset=0)
        assert cursor.execute.call_args.args[1][-2:] == (2, 0)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
    writer.assert_not_called()
    conn.close.assert_called_once()
