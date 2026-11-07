"""Real local signature verification; notifications remain non-authoritative."""
import ast
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import time

import pytest

from src.ai.billing import stripe_api
from src.ai.billing.payment_contracts import InvalidPaymentWebhook, PaymentEventKind as Kind, ProviderReference as Ref
from src.ai.billing.stripe_webhooks import StripeWebhookDecoder, _KINDS


SECRET = "whsec_offline_decoder_test"


def signed(event, *, timestamp=None):
    payload = json.dumps(event, ensure_ascii=False, indent=2).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(SECRET.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


def event(kind, obj):
    return {"object": "event", "id": "evt_original", "type": kind, "created": 1800000000,
            "data": {"object": obj}, "livemode": False}


@pytest.mark.parametrize("name,kind,obj,reference_field,reference_id", [
    ("checkout.session.completed", Kind.CHECKOUT_COMPLETED,
     {"id": "cs_test_one", "customer": "cus_one", "subscription": "sub_one", "invoice": "in_one"}, "checkout", "cs_test_one"),
    ("checkout.session.expired", Kind.CHECKOUT_EXPIRED, {"id": "cs_test_one"}, "checkout", "cs_test_one"),
    *[(name, Kind.SUBSCRIPTION_CHANGED, {"id": "sub_one", "customer": {"id": "cus_one"}}, "subscription", "sub_one")
      for name, mapped in _KINDS.items() if mapped == Kind.SUBSCRIPTION_CHANGED],
    *[(name, Kind.INVOICE_FAILED if name.endswith("failed") else Kind.INVOICE_SETTLED,
       {"id": "in_one", "customer": "cus_one", "parent": {"subscription_details": {"subscription": {"id": "sub_one"}}}},
       "invoice", "in_one") for name, mapped in _KINDS.items() if mapped in (Kind.INVOICE_SETTLED, Kind.INVOICE_FAILED)],
    *[(name, Kind.SCHEDULE_ENDED, {"id": "sched_one", "released_subscription": "sub_one"}, "schedule", "sched_one")
      for name, mapped in _KINDS.items() if mapped == Kind.SCHEDULE_ENDED],
])
def test_every_current_event_translates_with_original_identity_and_evidence(name, kind, obj, reference_field, reference_id):
    original = event(name, obj)
    payload, signature = signed(original)
    decoded = StripeWebhookDecoder(SECRET).decode(payload, signature)
    assert decoded.event_id == "evt_original" and decoded.provider == "stripe" and decoded.kind == kind
    assert getattr(decoded, reference_field) == Ref("stripe", reference_id)
    assert decoded.raw_payload == payload and decoded.raw_evidence == original
    if obj.get("subscription") or obj.get("parent") or obj.get("released_subscription"):
        assert decoded.subscription == Ref("stripe", "sub_one")
    if obj.get("customer"):
        assert decoded.customer == Ref("stripe", "cus_one")
    if obj.get("invoice"):
        assert decoded.invoice == Ref("stripe", "in_one")


@pytest.mark.parametrize("shape", ["subscription", "subscription_details", "parent"])
def test_invoice_reference_shapes_remain_supported(shape):
    obj = {"id": "in_one"}
    obj[shape] = ("sub_one" if shape == "subscription" else {"subscription": "sub_one"}
                  if shape == "subscription_details" else {"subscription_details": {"subscription": "sub_one"}})
    assert StripeWebhookDecoder(SECRET).decode(*signed(event("invoice.paid", obj))).subscription == Ref("stripe", "sub_one")


@pytest.mark.parametrize("invalid", ["missing", "wrong_secret", "tampered", "expired", "malformed", "missing_id"])
def test_invalid_signature_or_payload_emits_no_verified_event(invalid):
    original = event("invoice.paid", {"id": "in_one"})
    if invalid == "missing_id":
        del original["id"]
    payload, signature = signed(original, timestamp=1 if invalid == "expired" else None)
    if invalid == "missing":
        signature = ""
    elif invalid == "wrong_secret":
        signature = signature[:-64] + "0" * 64
    elif invalid == "tampered":
        payload += b" "
    elif invalid == "malformed":
        payload = b"invalid json"
    with pytest.raises(InvalidPaymentWebhook):
        StripeWebhookDecoder(SECRET).decode(payload, signature)


def test_unknown_verified_event_keeps_raw_evidence_without_inventing_a_subscription():
    original = event("future.provider.event", {"id": "some_resource", "metadata": {"tenant_id": "untrusted-hint"}})
    result = StripeWebhookDecoder(SECRET).decode(*signed(original))
    assert result.kind == Kind.UNKNOWN and result.subscription is None
    assert result.raw_evidence == original


def test_raw_evidence_is_copied_and_only_verified_bytes_reach_translation(monkeypatch):
    original = event("customer.subscription.updated", {"id": "sub_one", "metadata": {"tenant_id": "tenant-A"}})
    saved, calls = deepcopy(original), []
    def verify(payload, signature, secret):
        calls.append((payload, signature, secret))
        return original
    monkeypatch.setattr(stripe_api, "construct_event", verify)
    result = StripeWebhookDecoder(SECRET).decode(b"exact\r\nbytes", "signature")
    original["data"]["object"]["metadata"].clear()
    assert calls == [(b"exact\r\nbytes", "signature", SECRET)]
    assert result.raw_evidence == saved


def test_event_mapping_covers_exactly_the_existing_handled_event_set():
    assert set(_KINDS) == {
        "checkout.session.completed", "checkout.session.expired", "invoice.paid",
        "invoice.payment_succeeded", "invoice.payment_failed", "customer.subscription.created",
        "customer.subscription.updated", "customer.subscription.deleted", "customer.subscription.paused",
        "customer.subscription.resumed", "customer.subscription.trial_will_end",
        "customer.subscription.pending_update_applied", "customer.subscription.pending_update_expired",
        "subscription_schedule.released", "subscription_schedule.completed",
        "subscription_schedule.canceled", "subscription_schedule.aborted",
    }


def test_payment_boundary_wiring_is_scoped_and_contract_has_no_infrastructure_imports():
    src = Path(__file__).resolve().parents[2] / "src"
    new_modules = {"payment_contracts", "stripe_gateway", "stripe_webhooks", "payment_runtime"}
    for path in src.rglob("*.py"):
        if "tests" in path.parts or path.stem in new_modules:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {alias.name.split(".")[-1] for alias in node.names}
                module = (getattr(node, "module", None) or "").split(".")[-1]
                used = (names | {module}) & new_modules
                if used:
                    assert path.relative_to(src).as_posix() in {
                        "ai/billing/service.py", "ai/billing/checkout_attempts.py",
                        "ai/billing/webhooks.py", "ai/billing/store.py", "ai/billing/promotions.py",
                        "ai/routers/billing.py",
                        "ai/billing/payment_bindings.py", "ai/billing/trial_checkouts.py",
                    }, str(path)
                    assert "stripe_webhooks" not in used, "Provider decoding is composed at payment_runtime"
    contracts = ast.parse((src / "ai/billing/payment_contracts.py").read_text(encoding="utf-8"))
    imports = {node.module.split(".")[0] for node in ast.walk(contracts) if isinstance(node, ast.ImportFrom)}
    assert imports <= {"dataclasses", "datetime", "decimal", "enum", "typing"}


def test_dormant_reservation_repositories_are_not_imported_by_runtime_flows():
    from src.ai.billing import service, store, webhooks
    from src.ai.routers import auth, billing
    for module in (service, store, webhooks, auth, billing):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported = {alias.name.split(".")[-1] for alias in node.names}
                imported.add((getattr(node, "module", None) or "").split(".")[-1])
                assert not imported & {"payment_bindings", "trial_checkouts"}
