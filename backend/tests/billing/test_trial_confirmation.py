"""Offline B4 boundaries; no provider, database or activation execution."""
import ast
from pathlib import Path
import pytest
from src.ai.billing import trial_confirmation as T
from .test_provider_verification_contracts import observation


def test_incomplete_or_stored_evidence_cannot_reach_database():
    from dataclasses import replace
    from src.ai.billing import payment_contracts as C
    repo=object.__new__(T.TrialConfirmationRepository)
    for value in (replace(observation(),outcome=C.VerificationOutcome.PENDING),
                  replace(observation(),provenance=replace(observation().provenance,stored_observation_id='stored-observation'))):
        with pytest.raises(T.ConfirmationError,match='authoritative_trial_evidence'):
            repo.attest({},value,'consent',checkout_completed_at=value.provenance.observed_at,checkout_expires_at=value.trial.ends_at)
    # Checkout is COMPLETE in this fixture, but missing provider trial evidence
    # is rejected by the immutable contract before the SQL repository is reached.
    with pytest.raises(ValueError,match='complete recurring evidence'):
        replace(observation(),trial=None)


def test_confirmation_module_is_dormant_and_has_no_provider_or_credential_resolution():
    root=Path(__file__).resolve().parents[2]/'src'
    for path in root.rglob('*.py'):
        if 'tests' in path.parts or path.name=='trial_confirmation.py':continue
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').endswith('trial_confirmation'),str(path)
                assert not any(n.name=='trial_confirmation' for n in node.names),str(path)
            if isinstance(node,ast.Import):assert not any(n.name.endswith('trial_confirmation') for n in node.names),str(path)
    source=(root/'ai/billing/trial_confirmation.py').read_text()
    assert all(s not in source for s in ('import stripe','os.environ','system_connection','payment_gateway('))


def test_forward_migration_preserves_receipts_and_dormant_consent_authority():
    root=Path(__file__).resolve().parents[2]
    text=(root/'src/infrastructure/database/migrations/20261204000000_trusted_trial_confirmation.sql').read_text()
    assert "p #- '{payment_method,observed_at}'" in text
    assert 'UPDATE public.billing_verification_observations' not in text
    assert 'GRANT INSERT ON public.billing_trial_consents' not in text
    assert "b.environment<>'test'" in text
    assert 'CREATE ROLE %I NOLOGIN NOINHERIT' in text
