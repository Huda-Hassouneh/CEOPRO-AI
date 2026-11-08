"""Offline B3 type, privacy and dormant-boundary checks."""
import ast
from dataclasses import replace,FrozenInstanceError
from datetime import datetime,timezone
from pathlib import Path
import uuid

import pytest
from src.ai.billing import verification_observations as V
from src.ai.billing import payment_contracts as C
from .test_provider_verification_contracts import observation,request


def test_normalized_document_contains_only_typed_immutable_evidence():
    value=observation()
    document=V.evidence_document(value)
    assert document['recurring_authority']['consent']=='recorded'  # Data only; B3 SQL rejects unsupported local provenance.
    frozen=C.CustomerPayload.freeze(document)
    document['terms']['amount']='9999'
    assert frozen.unpack()['terms']['amount']!='9999'
    assert 'client_secret' not in frozen.canonical.decode()


@pytest.mark.parametrize('value',[{},None,True,object()])
def test_untyped_payloads_are_not_accepted_as_provider_observations(value):
    with pytest.raises(ValueError,match='Unsupported verification value type'):
        V.evidence_document(value)


def test_missing_frozen_context_and_arbitrary_connections_are_rejected():
    with pytest.raises(V.ObservationError,match='frozen_context'):
        V.request_document(request())


def test_dormant_persistence_has_no_runtime_consumers_or_provider_calls():
    root=Path(__file__).resolve().parents[2]/'src'
    for path in root.rglob('*.py'):
        if 'tests' in path.parts or path.name=='verification_observations.py':continue
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').endswith('verification_observations'),str(path)
                assert not any(n.name=='verification_observations' for n in node.names),str(path)
            if isinstance(node,ast.Import):assert not any(n.name.endswith('verification_observations') for n in node.names),str(path)
    source=(root/'ai/billing/verification_observations.py').read_text()
    assert all(name not in source for name in ('import stripe','stripe_verification','billing_setup_trial','confirm_trial','system_connection'))


def test_migration_is_forward_only_and_has_no_activation_or_runtime_grants():
    root=Path(__file__).resolve().parents[2]
    files=list((root/'src/infrastructure/database/migrations').glob('*.sql'))
    assert len(files)==169
    source=next(p for p in files if p.name=='20261203000000_trusted_trial_observations.sql').read_text()
    assert source.count('CREATE ROLE %I NOLOGIN')==1
    for forbidden in ('INSERT INTO public.billing_trials','INSERT INTO public.billing_subscriptions',
                      'INSERT INTO public.tenant_plan_assignments','INSERT INTO public.tenant_credit_balances','CREATE FUNCTION public.billing_trial_confirm'):
        assert forbidden not in source
    assert 'TO ceopro_billing_setup;' not in source and 'TO ceopro_billing_webhook;' not in source
