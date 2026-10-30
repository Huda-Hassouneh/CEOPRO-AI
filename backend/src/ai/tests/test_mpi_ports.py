"""Port substitution and real adapter functions; native MPI tests retain DB truth."""
import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest

from src.ai.mpi import application, data_access, evidence, pipeline
from src.ai.mpi.ports import EvidenceWriter, HistoryReader, ReviewReader


@pytest.mark.parametrize('count,category', [(0, 'UNKNOWN'), (1, 'FACT'), (5, 'FACT')])
def test_summary_consumes_ports_and_keeps_pipeline_commit(monkeypatch, count, category):
    conn = MagicMock()
    events, written = [], []
    monkeypatch.setattr(data_access, 'validate_subject', lambda *args: events.append('validate'))
    monkeypatch.setattr(data_access, 'load_country_context', lambda *args: events.append('country') or 'JO')
    monkeypatch.setattr(data_access, 'load_scored_reviews', MagicMock(side_effect=AssertionError('direct read')))
    monkeypatch.setattr(evidence, 'insert_evidence_record', MagicMock(side_effect=AssertionError('direct write')))
    reviews = [dict(review_id=str(i), label='positive', positive_probability=.9,
                    negative_probability=.1, effective_date=date(2020, 1, 1),
                    collection_method='PUBLIC_API') for i in range(count)]

    def read(subject_type, subject_id=None):
        assert (subject_type, subject_id) == ('BUSINESS', None)
        events.append('read')
        return reviews

    def write(category, source_module, source_record_ids, confidence_score,
              explanation_text, model_version, country_context=None):
        conn.commit.assert_not_called()
        events.append('write')
        written.append((category, source_record_ids, country_context))
        return 'e'

    reader: ReviewReader = read
    writer: EvidenceWriter = write
    conn.commit.side_effect = lambda: events.append('commit')
    result = pipeline.get_subject_mpi(conn, 'tenant', 'BUSINESS', as_of=date(2020, 1, 1),
                                      review_reader=reader, evidence_writer=writer)
    assert events == ['validate', 'read', 'country', 'write', 'commit']
    assert result['evidence_id'] == 'e'
    assert result['status'] == ('OK' if count else 'UNKNOWN')
    assert written[0][0] == category and written[0][2] == 'JO'
    assert written[0][1]['eligible_review_count'] == count
    conn.commit.assert_called_once()
    conn.cursor.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


def test_history_consumes_port_after_validation_without_transaction(monkeypatch):
    conn, events = MagicMock(), []
    monkeypatch.setattr(data_access, 'validate_subject', lambda *args: events.append('validate'))
    monkeypatch.setattr(data_access, 'load_history', MagicMock(side_effect=AssertionError('direct history')))
    rows = [('e', datetime(2020, 1, 1, tzinfo=timezone.utc), {}, None, 'text')]

    def read(subject_type, canonical_subject, limit, offset):
        assert (subject_type, canonical_subject, limit, offset) == ('BUSINESS', None, 3, 4)
        events.append('read')
        return rows

    reader: HistoryReader = read
    assert application.get_history(conn, 'tenant', 'BUSINESS', limit=2, offset=4,
                                   history_reader=reader) is rows
    assert events == ['validate', 'read']
    assert conn.mock_calls == []


def test_comparison_uses_review_port_for_both_subjects(monkeypatch):
    monkeypatch.setattr(data_access, 'validate_subject', lambda *args: None)
    reader = MagicMock(return_value=[])
    conn = MagicMock()
    comparison = pipeline.compare_subjects(conn, 'tenant', ('BUSINESS', None),
                                           ('PRODUCT', 'product'), review_reader=reader)
    assert [call.args for call in reader.call_args_list] == [('BUSINESS', None), ('PRODUCT', 'product')]
    assert comparison.comparable is False and comparison.difference is None
    assert conn.mock_calls == []


def _adapter_call(kind, conn):
    if kind == 'review':
        return data_access.review_reader(conn, 'tenant')('PRODUCT', 'product')
    if kind == 'history':
        return data_access.history_reader(conn, 'tenant', 'ai.mpi')('PRODUCT', 'product', 3, 4)
    return evidence.evidence_writer(conn, 'tenant')(
        'UNKNOWN', 'ai.mpi', {'status': 'UNKNOWN'}, None, 'text', None, 'JO')


@pytest.mark.parametrize('kind', ['review', 'history', 'evidence'])
def test_bound_postgres_adapters_keep_arguments_results_and_ownership(kind):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = ('e',)
    assert _adapter_call(kind, conn) == ('e' if kind == 'evidence' else [])
    params = cursor.execute.call_args.args[1]
    if kind == 'review':
        assert params == ['tenant', 'PRODUCT', 'product']
    elif kind == 'history':
        assert params == ('tenant', 'ai.mpi', 'PRODUCT', 'product', 'PRODUCT', 'tenant', 3, 4)
    else:
        assert params[:3] == ('tenant', 'UNKNOWN', 'ai.mpi')
        assert json.loads(params[3]) == {'status': 'UNKNOWN'}
        assert params[4:] == (None, 'text', None, 'JO')
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('kind', ['review', 'history', 'evidence'])
def test_bound_adapters_propagate_database_errors_without_transaction(kind):
    conn = MagicMock()
    error = psycopg2.OperationalError('synthetic')
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = error
    with pytest.raises(psycopg2.OperationalError) as raised:
        _adapter_call(kind, conn)
    assert raised.value is error
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('failure', ['read', 'write'])
def test_pipeline_port_errors_propagate_before_commit(monkeypatch, failure):
    monkeypatch.setattr(data_access, 'validate_subject', lambda *args: None)
    monkeypatch.setattr(data_access, 'load_country_context', lambda *args: None)
    error, conn = psycopg2.OperationalError('synthetic'), MagicMock()
    reader = MagicMock(return_value=[], side_effect=error if failure == 'read' else None)
    writer = MagicMock(side_effect=error)
    with pytest.raises(psycopg2.OperationalError) as raised:
        pipeline.get_subject_mpi(conn, 'tenant', 'BUSINESS', review_reader=reader, evidence_writer=writer)
    assert raised.value is error
    if failure == 'read':
        writer.assert_not_called()
    assert conn.mock_calls == []
