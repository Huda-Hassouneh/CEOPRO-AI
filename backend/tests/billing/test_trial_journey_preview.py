"""B2a HTTP/auth/projection tests; checkpoint SQL reuses accepted native B1 proof."""
import ast
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from src.ai import db
from src.ai.billing import trial_coordinator as J
from src.ai.core import security


@pytest.fixture
def preview(monkeypatch):
    operation, tenant, actor = [str(uuid4()) for _ in range(3)]
    terms = dict(plan_key='growth', currency='USD', interval_months=3,
        trial_duration_days=14, approved_amount=Decimal('12345678901234.123456789'))
    row = dict(reservation=dict(terms, attempt_id=operation, tenant_id=tenant,
        started_by_user_id=actor, binding_id='original-binding', state='pending',
        approved_terms=dict(terms, binding=dict(provider='stripe', environment='test',
            merchant_account_id='private-merchant', binding_id='original-binding'))),
        checkout=dict(attempt_id=operation, tenant_id=tenant, state='preparing',
            gateway_binding_id='original-binding', first_submitted_at=None, provider_session_id=None,
            provider_params={'private-token': 'never-expose'}))
    monkeypatch.setenv('RECURRING_JOURNEY_PREVIEW_ENABLED', 'true')
    monkeypatch.setenv('REQUIRE_EMAIL_VERIFICATION', 'false')
    principal = Mock()
    monkeypatch.setattr(security, 'assert_active_principal', principal)
    monkeypatch.setattr(security, 'sessions_invalidated_since', lambda _: 0)
    monkeypatch.setattr(J, '_setup', Mock())
    load = Mock(side_effect=lambda _: deepcopy(row))
    monkeypatch.setattr(J.ReservationRepository, 'load', load)
    connection = Mock()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(db, 'billing_preview_connection', factory)
    for name in ('start', 'present', 'advance'):
        monkeypatch.setattr(J.TrialCoordinator, name, Mock(side_effect=AssertionError('Mutation forbidden')))
    token, _ = security.create_access_token(tenant, actor, email_verified=True)
    return dict(operation=operation, tenant=tenant, actor=actor, row=row, load=load,
        factory=factory, connection=connection, principal=principal,
        headers={'Authorization': 'Bearer '+token})


def get(client, p, suffix=''):
    return client.get('/billing/trial-journeys/'+p['operation']+suffix, headers=p['headers'])


def test_authentication_precedes_disabled_route(client, preview, monkeypatch):
    monkeypatch.delenv('RECURRING_JOURNEY_PREVIEW_ENABLED')
    assert client.get('/billing/trial-journeys/'+preview['operation']).status_code == 401
    assert get(client, preview).status_code == 404
    preview['factory'].assert_not_called()
    preview['load'].assert_not_called()


@pytest.mark.parametrize('flag', ['', 'false', '1', 'yes'])
def test_only_explicit_feature_enablement(client, preview, monkeypatch, flag):
    monkeypatch.setenv('RECURRING_JOURNEY_PREVIEW_ENABLED', flag)
    assert get(client, preview).status_code == 404
    preview['factory'].assert_not_called()


def test_frozen_safe_exact_preview_and_no_client_override(client, preview):
    p = preview
    response = get(client, p, '?tenant_id=attacker&approved_amount=0&binding_id=attacker')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['vary'] == 'Authorization'
    value = response.json()
    assert value == dict(operation_id=p['operation'], state='eligible', reason='reserved_terms_available',
        commercial_terms=dict(plan_key='growth', renewal_amount='12345678901234.123456789',
            currency='USD', interval_months=3, trial_duration_days=14))
    p['factory'].assert_called_once_with(p['tenant'], p['actor'])
    p['principal'].assert_called_once_with(p['tenant'], p['actor'], 0)
    p['load'].assert_called_once()
    assert str(p['load'].call_args.args[0]) == p['operation']
    p['connection'].close.assert_called_once()
    assert all(value not in response.text for value in ('private-', 'original-binding', 'never-expose', 'VERIFIED', 'hasAccess'))


@pytest.mark.parametrize('case,expected', [('ambiguous','pending_verification'), ('known','pending_verification'),
    ('expired','expired'), ('released','blocked'), ('confirmed','blocked'), ('binding','conflict')])
def test_checkpoint_states_never_activate(client, preview, case, expected):
    r, a = preview['row']['reservation'], preview['row']['checkout']
    if case == 'ambiguous': a['first_submitted_at'] = 'persisted-time'
    if case == 'known': a['provider_session_id'] = 'private-checkout'
    if case == 'expired': a['state'] = 'expired'
    if case in ('released','confirmed'): r['state'] = case
    if case == 'binding': a['gateway_binding_id'] = 'other-binding'
    response = get(client, preview)
    assert response.status_code == 200 and response.json()['state'] == expected
    if case == 'binding': assert response.json()['commercial_terms'] is None


@pytest.mark.parametrize('key,value', [('approved_amount',Decimal('0')), ('currency','EUR'),
    ('interval_months',12), ('trial_duration_days',99), ('plan_key','enterprise')])
def test_frozen_term_contradiction_hides_commercial_preview(client, preview, key, value):
    preview['row']['reservation']['approved_terms'][key] = value
    response = get(client, preview).json()
    assert response['state'] == 'conflict' and response['commercial_terms'] is None


@pytest.mark.parametrize('scope', ['tenant', 'checkout_tenant', 'actor', 'operation'])
def test_defense_in_depth_scope_refusal(client, preview, scope):
    r, a = preview['row']['reservation'], preview['row']['checkout']
    if scope == 'tenant': r['tenant_id'] = str(uuid4())
    if scope == 'checkout_tenant': a['tenant_id'] = str(uuid4())
    if scope == 'actor': r['started_by_user_id'] = str(uuid4())
    if scope == 'operation': r['attempt_id'] = str(uuid4())
    assert get(client, preview).status_code == 404


def test_absent_unauthorized_or_revoked_checkpoint_is_hidden(client, preview):
    preview['load'].side_effect = lambda _: None
    assert get(client, preview).status_code == 404


def test_current_auth_revocation_denies_before_preview_socket(client, preview):
    preview['principal'].side_effect = HTTPException(403, 'revoked')
    assert get(client, preview).status_code == 403
    preview['factory'].assert_not_called()


def test_signed_out_session_denied(client, preview, monkeypatch):
    monkeypatch.setattr(security, 'is_token_revoked', lambda *a, **k: True)
    assert get(client, preview).status_code == 401
    preview['factory'].assert_not_called()


def test_database_failure_sanitized_and_connection_closed(client, preview):
    preview['load'].side_effect = RuntimeError('private-database-password')
    response = get(client, preview)
    assert response.status_code == 503 and 'private' not in response.text
    preview['connection'].close.assert_called_once()



def test_missing_restricted_credential_is_unavailable_without_fallback(client, preview):
    preview['factory'].side_effect = RuntimeError('private-credential-unavailable')
    response = get(client, preview)
    assert response.status_code == 503 and 'private' not in response.text
    preview['load'].assert_not_called()


def test_invalid_operation_and_write_methods_refused(client, preview):
    assert client.get('/billing/trial-journeys/latest', headers=preview['headers']).status_code == 422
    for method in ('post', 'put', 'delete'):
        assert getattr(client, method)('/billing/trial-journeys/'+preview['operation'], headers=preview['headers']).status_code == 405
    preview['load'].assert_not_called()


def test_strict_readonly_factory_has_no_admin_fallback(monkeypatch):
    monkeypatch.delenv('BILLING_SETUP_DB_PASSWORD', raising=False)
    fallback = Mock(side_effect=AssertionError('No administrative connection'))
    monkeypatch.setattr(db, 'system_connection', fallback)
    socket = Mock(); monkeypatch.setattr(db, '_service_socket', socket)
    with pytest.raises(RuntimeError, match='credential unavailable'):
        db.billing_preview_connection(str(uuid4()), str(uuid4()))
    fallback.assert_not_called(); socket.assert_not_called()


def test_readonly_socket_and_exact_json_decoder(monkeypatch):
    from psycopg2 import extras
    raw = Mock(); socket = Mock(return_value=raw)
    monkeypatch.setenv('BILLING_SETUP_DB_PASSWORD', 'synthetic-test-only')
    monkeypatch.setattr(db, '_service_socket', socket)
    register = Mock(); monkeypatch.setattr(extras, 'register_default_jsonb', register)
    wrapper = Mock(); monkeypatch.setattr(db, '_BillingSetupConnection', wrapper)
    db.billing_preview_connection('tenant', 'actor')
    socket.assert_called_once_with('ceopro_billing_setup', 'synthetic-test-only')
    raw.set_session.assert_called_once_with(readonly=True)
    decode = register.call_args.kwargs['loads']
    assert decode('{"amount":12345678901234.123456789}')['amount'] == Decimal('12345678901234.123456789')
    assert wrapper.call_args.args[1:] == (raw, 'tenant', 'actor')


def test_readonly_setup_failure_closes_socket(monkeypatch):
    raw = Mock(); raw.set_session.side_effect = RuntimeError('unavailable')
    monkeypatch.setenv('BILLING_SETUP_DB_PASSWORD', 'synthetic')
    monkeypatch.setattr(db, '_service_socket', Mock(return_value=raw))
    with pytest.raises(RuntimeError): db.billing_preview_connection('tenant', 'actor')
    raw.close.assert_called_once()


def test_only_status_and_load_are_exposed_in_new_coordinator_consumer():
    source = Path(__file__).resolve().parents[2]/'src/ai/routers/trial_journey_preview.py'
    tree = ast.parse(source.read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert 'status' in calls and 'load' in calls
    assert not calls & {'start','present','advance','accept','associate','reserve','claim','confirm','attest','execute','system_connection','billing_setup_connection'}
    assert not any(isinstance(n, (ast.Import,ast.ImportFrom)) and 'trial_confirmation' in ast.unparse(n) for n in ast.walk(tree))
