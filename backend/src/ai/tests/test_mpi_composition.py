"""Remaining capability seams and default PostgreSQL binding contracts."""
from datetime import date
from unittest.mock import MagicMock

import psycopg2
import pytest

from src.ai.mpi import application, data_access, pipeline, postgres


@pytest.mark.parametrize('scope', ['BUSINESS', 'PRODUCT', 'COMPETITOR'])
@pytest.mark.parametrize('count', [0, 1])
def test_summary_substitutes_all_side_effects_and_keeps_commit(monkeypatch, scope, count):
    conn, events = MagicMock(), []
    for name in ('subject_validator', 'review_reader', 'country_reader', 'evidence_writer'):
        monkeypatch.setattr(postgres, name, MagicMock(side_effect=AssertionError('unexpected default')))
    subject = None if scope == 'BUSINESS' else 'subject'
    reviews = [dict(review_id='r', label='positive', positive_probability=.9, negative_probability=.1,
                    effective_date=date(2020, 1, 1), collection_method='PUBLIC_API')] * count

    def validate(subject_type, subject_id=None):
        assert (subject_type, subject_id) == (scope, subject)
        events.append('validate')

    def country(subject_type, subject_id=None):
        assert (subject_type, subject_id) == (scope, subject)
        events.append('country')
        return 'JO'

    def write(*args):
        conn.commit.assert_not_called()
        assert args[0] == ('FACT' if count else 'UNKNOWN')
        assert args[-1] == 'JO'
        events.append('write')
        return 'e'

    conn.commit.side_effect = lambda: events.append('commit')
    result = pipeline.get_subject_mpi(
        conn, 'tenant', scope, subject, as_of=date(2020, 1, 1), subject_validator=validate,
        country_reader=country, review_reader=lambda *args: events.append('reviews') or reviews,
        evidence_writer=write,
    )
    assert result['evidence_id'] == 'e'
    assert events == ['validate', 'reviews', 'country', 'write', 'commit']
    conn.commit.assert_called_once()
    conn.cursor.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('scope,subject,canonical', [
    ('BUSINESS', 'tenant', None),
    ('PRODUCT', 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
    ('COMPETITOR', 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
])
def test_history_subject_substitution_retains_canonicalization(scope, subject, canonical):
    conn, events = MagicMock(), []
    def validate(*args):
        assert args == (scope, subject)
        events.append('validate')
    def read(*args):
        assert args == (scope, canonical, 21, 0)
        events.append('read')
        return []
    assert application.get_history(conn, 'tenant', scope, subject,
                                   subject_validator=validate, history_reader=read) == []
    assert events == ['validate', 'read']
    assert conn.mock_calls == []


def test_comparison_substitutes_subject_validation():
    conn, events = MagicMock(), []
    def validate(*args):
        events.append(('validate', args))
    def read(*args):
        events.append(('read', args))
        return []
    pipeline.compare_subjects(conn, 'tenant', ('BUSINESS', None), ('PRODUCT', 'product'),
                              subject_validator=validate, review_reader=read)
    assert events == [('validate', ('BUSINESS', None)), ('read', ('BUSINESS', None)),
                      ('validate', ('PRODUCT', 'product')), ('read', ('PRODUCT', 'product'))]
    assert conn.mock_calls == []


def test_default_binding_is_inert():
    conn = MagicMock()
    postgres.subject_validator(conn, 'tenant')
    postgres.country_reader(conn, 'tenant')
    postgres.review_reader(conn, 'tenant')
    postgres.evidence_writer(conn, 'tenant')
    postgres.history_reader(conn, 'tenant', 'ai.mpi')
    assert conn.mock_calls == []


@pytest.mark.parametrize('kind,row,expected', [('subject', (1,), None), ('country', ('JO',), 'JO'),
                                             ('country', None, None)])
def test_new_default_capabilities_use_existing_transaction(kind, row, expected):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    capability = postgres.subject_validator if kind == 'subject' else postgres.country_reader
    assert capability(conn, 'tenant')('BUSINESS', None) == expected
    assert cursor.execute.call_args.args[1] == ('tenant',)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('factory', [postgres.subject_validator, postgres.country_reader])
def test_new_default_capabilities_preserve_database_error_identity(factory):
    conn, error = MagicMock(), psycopg2.OperationalError('synthetic')
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = error
    with pytest.raises(psycopg2.OperationalError) as raised:
        factory(conn, 'tenant')('BUSINESS')
    assert raised.value is error
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()


@pytest.mark.parametrize('operation', ['summary', 'history', 'comparison', 'country'])
def test_substituted_errors_propagate_before_commit(operation):
    conn = MagicMock()
    error = data_access.SubjectNotFoundError('MPI subject not found.')
    fail = MagicMock(side_effect=error)
    read, write = MagicMock(return_value=[]), MagicMock()
    with pytest.raises(data_access.SubjectNotFoundError) as raised:
        if operation == 'history':
            application.get_history(conn, 'tenant', 'BUSINESS', subject_validator=fail, history_reader=read)
        elif operation == 'comparison':
            pipeline.compare_subjects(conn, 'tenant', ('BUSINESS', None), ('PRODUCT', 'p'),
                                      subject_validator=fail, review_reader=read)
        else:
            pipeline.get_subject_mpi(conn, 'tenant', 'BUSINESS', review_reader=read, evidence_writer=write,
                                     subject_validator=(lambda *args: None) if operation == 'country' else fail,
                                     country_reader=fail)
    assert raised.value is error
    write.assert_not_called()
    if operation != 'country':
        read.assert_not_called()
    assert conn.mock_calls == []
