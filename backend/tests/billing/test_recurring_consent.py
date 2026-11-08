"""Offline A1 contract/boundary checks; no real customer consent."""
import ast
from pathlib import Path
import uuid

import pytest
from src.ai.billing import recurring_consent as R


@pytest.mark.parametrize('digest', ['', 'sha256:'+'a'*63, 'sha256:'+'A'*64, None])
def test_full_canonical_digest_required(digest):
    with pytest.raises(ValueError):
        R.PresentationIdentity(uuid.uuid4(), digest)


def test_identity_and_input_validation_before_persistence():
    identity = R.PresentationIdentity(uuid.uuid4(), 'sha256:'+'a'*64)
    with pytest.raises(R.ConsentError):
        R.PresentationIdentity(str(identity.presentation_id), identity.terms_digest)
    repo = object.__new__(R.ConsentRepository)
    with pytest.raises(R.ConsentError):
        repo.accept(identity, 'untrusted-short-challenge')
    with pytest.raises(R.ConsentError):
        repo.invalidate(uuid.uuid4(), R.ConsentState.ACCEPTED)


def test_dormant_import_and_provider_boundaries():
    root = Path(__file__).resolve().parents[2]/'src'
    for path in root.rglob('*.py'):
        if 'tests' in path.parts or path.name == 'recurring_consent.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').endswith('recurring_consent'), str(path)
                assert not any(n.name == 'recurring_consent' for n in node.names), str(path)
            if isinstance(node, ast.Import):
                assert not any(n.name.endswith('recurring_consent') for n in node.names), str(path)
    source = (root/'ai/billing/recurring_consent.py').read_text()
    assert all(s not in source for s in ('import stripe', 'os.environ', 'system_connection', 'payment_gateway(', 'SET ROLE'))


def test_migration_has_no_commercial_seed_or_access_mutations():
    path = Path(__file__).resolve().parents[2]/'src/infrastructure/database/migrations/20261205000000_recurring_consent_foundation.sql'
    text = path.read_text()
    assert 'INSERT INTO public.billing_consent_policy_versions' not in text
    for table in ('billing_trials', 'billing_subscriptions', 'tenant_plan_assignments', 'tenant_credit_balances',
                  'usage_ledger', 'billing_verification_observations', 'billing_trial_attestations', 'billing_trial_confirmations'):
        assert 'INSERT INTO public.'+table not in text
        assert 'UPDATE public.'+table not in text
    assert 'GRANT EXECUTE ON FUNCTION public.billing_confirmation_' not in text
