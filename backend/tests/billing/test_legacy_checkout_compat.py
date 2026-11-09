"""Legacy Stripe recovery on canonical reservations; no provider network."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.ai.billing import checkout_attempts, service, store
from src.ai.billing.payment_contracts import CheckoutState, PaymentProviderError, ProviderOperationOutcome, SubscriptionState


@pytest.fixture
def pending(monkeypatch, memory_checkout_reservations):
    row = checkout_attempts.reserve(None, 'tenant', 'original', 'growth', 'monthly')
    row.update(session_id='cs_original', params={'original': True})
    gateway = MagicMock(provider='stripe')
    monkeypatch.setattr(service, 'payment_gateway', lambda: gateway)
    return row, gateway, memory_checkout_reservations


@pytest.mark.parametrize('state', [CheckoutState.OPEN, CheckoutState.COMPLETE])
def test_cancel_keeps_fence_until_provider_confirms_closed(pending, state):
    row, gateway, rows = pending
    gateway.get_checkout.return_value = SimpleNamespace(state=CheckoutState.OPEN)
    gateway.expire_checkout.return_value = SimpleNamespace(state=state)
    with pytest.raises(service.BillingError) as error:
        service.cancel_pending_checkout(None, None, 'tenant')
    assert error.value.code == 'checkout_reconciling'
    assert rows['tenant'] == row


def test_cancel_verified_closed_preserves_original_identity(pending):
    row, gateway, rows = pending
    gateway.get_checkout.return_value = SimpleNamespace(state=CheckoutState.OPEN)
    gateway.expire_checkout.return_value = SimpleNamespace(state=CheckoutState.EXPIRED)
    assert service.cancel_pending_checkout(None, None, 'tenant')['state'] == 'checkout_cancelled'
    assert not rows
    assert gateway.expire_checkout.call_args.args[0].opaque_id == 'cs_original'


@pytest.mark.parametrize('outcome', [ProviderOperationOutcome.OUTCOME_UNKNOWN, ProviderOperationOutcome.UNAVAILABLE])
def test_cancel_uncertain_read_never_releases_fence(pending, outcome):
    row, gateway, rows = pending
    gateway.get_checkout.side_effect = PaymentProviderError(outcome)
    with pytest.raises(PaymentProviderError):
        service.cancel_pending_checkout(None, None, 'tenant')
    assert rows['tenant'] == row
    gateway.expire_checkout.assert_not_called()


def test_cancel_definitively_absent_session_closes_only_local_attempt(pending):
    _, gateway, rows = pending
    gateway.get_checkout.side_effect = PaymentProviderError(ProviderOperationOutcome.NOT_FOUND)
    assert service.cancel_pending_checkout(None, None, 'tenant')['state'] == 'checkout_cancelled'
    assert not rows
    gateway.expire_checkout.assert_not_called()


@pytest.mark.parametrize('frozen', [False, True])
def test_cancel_unsubmitted_only_if_request_was_never_frozen(pending, frozen):
    row, gateway, rows = pending
    row.update(session_id=None, params={'original': True} if frozen else None)
    if frozen:
        with pytest.raises(service.BillingError):
            service.cancel_pending_checkout(None, None, 'tenant')
        assert rows
    else:
        assert service.cancel_pending_checkout(None, None, 'tenant')['state'] == 'checkout_cancelled'
        assert not rows
    gateway.get_checkout.assert_not_called()


@pytest.mark.parametrize('frozen', [False, True])
def test_creation_error_releases_only_unsubmitted_checkout(monkeypatch, memory_checkout_reservations, frozen):
    monkeypatch.setattr(service, '_require_payments', lambda: None)
    monkeypatch.setattr(service.config, 'app_base_url', lambda: 'http://127.0.0.1:5173')
    monkeypatch.setattr(store, 'current_subscription', lambda *a: None)
    monkeypatch.setattr(store, 'trial', lambda *a: None)
    monkeypatch.setattr(service, '_price_or_error', lambda *a: {})
    original = []
    def fail(*args, **kw):
        attempt = kw['_attempt']; original.append(attempt['attempt_id'])
        if frozen:
            checkout_attempts.freeze(None, attempt, {'price': 'original'})
        raise TimeoutError('synthetic failure')
    monkeypatch.setattr(service, '_create_checkout', fail)
    with pytest.raises(TimeoutError):
        service.create_checkout(None, MagicMock(), 'tenant', 'synthetic@example.test', 'Synthetic', 'growth', 'monthly')
    assert bool(memory_checkout_reservations) == frozen
    if frozen:
        assert memory_checkout_reservations['tenant']['attempt_id'] == original[0]
        assert memory_checkout_reservations['tenant']['params'] == {'price': 'original'}


@pytest.mark.parametrize('prior', ['unsubmitted', 'expired', 'absent'])
def test_released_attempt_rechecks_existing_provider_contracts(monkeypatch, pending, prior):
    row, gateway, _ = pending
    monkeypatch.setattr(service, '_require_payments', lambda: None)
    monkeypatch.setattr(service.config, 'app_base_url', lambda: 'http://127.0.0.1:5173')
    monkeypatch.setattr(service, '_price_or_error', lambda *a: {})
    monkeypatch.setattr(store, 'current_subscription', lambda *a: None)
    monkeypatch.setattr(store, 'trial', lambda *a: None)
    monkeypatch.setattr(store, 'customer_id', lambda *a: 'cus_original')
    monkeypatch.setattr(service, '_check_clock_customer', lambda *a: None)
    create = MagicMock()
    monkeypatch.setattr(service, '_create_checkout', create)
    if prior == 'unsubmitted':
        row.update(session_id=None, params=None)
    elif prior == 'absent':
        gateway.get_checkout.side_effect = PaymentProviderError(ProviderOperationOutcome.NOT_FOUND)
    else:
        gateway.get_checkout.return_value = SimpleNamespace(state=CheckoutState.EXPIRED)
    gateway.list_customer_subscriptions.return_value = [SimpleNamespace(state=SubscriptionState.ACTIVE)]
    with pytest.raises(service.BillingError) as error:
        service.create_checkout(None, MagicMock(), 'tenant', 'synthetic@example.test', 'Synthetic', 'growth', 'monthly')
    assert error.value.code == 'checkout_reconciling'
    create.assert_not_called()
