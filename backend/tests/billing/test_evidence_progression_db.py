"""Dormant A2, synthetic provider evidence; native PG17 and real role passwords."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import uuid

import psycopg2
from psycopg2.extras import Json
import pytest
from src.ai.billing import payment_contracts as C, verification_observations as V, trial_confirmation as T
from .test_trial_confirmation_db import evidence, attest, confirm, expire_claim, customer_scenario, parties, restricted_runtime
from .test_verification_observations_db import connection
from .test_payment_bindings_db import fingerprint


@pytest.fixture
def progression(request, monkeypatch):
    # Reuse B4's canonical durable Customer/reservation fixture. Substitute only
    # its initial synthetic provider read, before any evidence is persisted.
    original = V.ObservationRepository.record
    def first_read(repo, row, identity, value, **kwargs):
        caps = C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED)
        if getattr(request, 'param', 'incomplete') == 'setup':
            value = replace(value, capabilities=caps, subscription_state=C.SubscriptionState.PENDING,
                payment_method=replace(value.payment_method, readiness=C.PaymentMethodReadiness.PENDING_SETUP),
                recurring_authorization=replace(value.recurring_authorization, readiness=C.PaymentMethodReadiness.PENDING_SETUP))
        else:
            value = replace(value, capabilities=caps, subscription=None, checkout_state=C.CheckoutState.OPEN,
                subscription_state=C.SubscriptionState.UNKNOWN, terms=None, trial=None,
                payment_method=None, recurring_authorization=None, cancel_at_period_end=None)
        return original(repo, row, identity, value, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(V.ObservationRepository, 'record', first_read)
        result = request.getfixturevalue('evidence')
    return result


def append(owner_db, context, value):
    party, _, claim, *_ = context
    expire_claim(owner_db, party, claim['operation_id'])
    with closing(connection(party)) as conn:
        repo = V.ObservationRepository(conn)
        stored = repo.record(repo.claim(repo.read(claim['operation_id'])), uuid.uuid4(), value)
        row = repo.read(claim['operation_id'])
        next_claim = repo.claim(row)
    return stored, row, (party, context[1], next_claim, value, context[4], context[5])


@pytest.mark.parametrize('progression', ['incomplete', 'setup'], indirect=True)
def test_pending_to_ready_preserves_history_and_only_allows_trusted_attestation(owner_db, progression):
    before = fingerprint(owner_db)
    stored, row, ready = append(owner_db, progression, progression[3])
    assert not row['has_conflict'] and row['state'] == 'observed'
    assertion = attest(ready)
    assert assertion['operation_id'] == row['operation_id']
    assert fingerprint(owner_db) == before  # Recording and attesting grant no rights.
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*),count(DISTINCT evidence_digest) FROM billing_verification_observations WHERE operation_id=%s', (row['operation_id'],))
        assert cur.fetchone() == (2, 2)
        cur.execute('SELECT evidence_digest FROM billing_verification_observations WHERE observation_id=%s', (stored.unpack()['observation_id'],))
        assert cur.fetchone()[0] == stored.unpack()['evidence_digest']


def test_consistent_repeats_and_stale_history_fence_old_attestation(owner_db, progression):
    before = fingerprint(owner_db)
    _, _, ready = append(owner_db, progression, progression[3])
    assertion = attest(ready)
    _, row, latest = append(owner_db, ready, ready[3])
    assert not row['has_conflict']
    with pytest.raises(T.ConfirmationError, match='confirmation_55000'):
        confirm(ready, assertion)
    assert attest(latest)['operation_id'] == row['operation_id']
    assert fingerprint(owner_db) == before


@pytest.mark.parametrize('section,key,value', [
    (None, 'customer', 'other'), (None, 'checkout', 'other'), (None, 'subscription', 'other'),
    ('terms', 'amount', '0'), ('terms', 'currency', 'JOD'), ('terms', 'quantity', 2),
    ('terms', 'interval_months', 12), ('terms', 'price', 'other'),
    ('trial', 'ends_at', '2030-01-01T00:00:00+00:00'),
    (None, 'cancel_at_period_end', True), (None, 'period_start', '2030-01-01T00:00:00+00:00'),
    ('payment_method', 'payment_method', 'other'), ('payment_method', 'source', 'other'),
    ('recurring_authority', 'source', 'other'), ('recurring_authority', 'kind', 'mandate'),
    ('recurring_authority', 'readiness', 'attached'),
    ('recurring_authority', 'consent', 'recorded'), ('capabilities', 'cancellation', 'unknown'),
])
def test_positive_facts_cannot_change_or_disappear(owner_db, evidence, section, key, value):
    old = V.evidence_document(evidence[3])
    old['period_start'] = evidence[3].trial.started_at.isoformat()
    old['period_end'] = evidence[3].trial.ends_at.isoformat()
    new = deepcopy(old)
    (new if section is None else new[section])[key] = value
    with owner_db.cursor() as cur:
        cur.execute('SELECT billing_confirmation_progresses(%s,%s)', (Json(old), Json(new)))
        assert cur.fetchone() == (False,)
        (new if section is None else new[section])[key] = None
        cur.execute('SELECT billing_confirmation_progresses(%s,%s)', (Json(old), Json(new)))
        assert cur.fetchone() == (False,)


@pytest.mark.parametrize('progression', ['setup'], indirect=True)
@pytest.mark.parametrize('change', ['subscription', 'payment_method', 'setup', 'trial'])
def test_contradictory_history_is_retained_and_cannot_be_hidden(owner_db, progression, change):
    base = progression[3]
    ref = lambda x: C.ProviderReference(base.request.binding.provider, x, binding=base.request.binding)
    if change == 'subscription':
        bad = replace(base, subscription=ref('sub_other'))
    elif change == 'payment_method':
        bad = replace(base, payment_method=replace(base.payment_method, payment_method=ref('pm_other')))
    elif change == 'setup':
        bad = replace(base, payment_method=replace(base.payment_method, source=ref('setup_other')),
                      recurring_authorization=replace(base.recurring_authorization, source=ref('setup_other')))
    else:
        window = base.trial
        bad = replace(base, trial=C.ObservedTrialWindow(window.started_at+timedelta(seconds=1), window.ends_at+timedelta(seconds=1), window.cutoff+timedelta(seconds=1)))
    _, row, conflict = append(owner_db, progression, bad)
    assert row['has_conflict'] and row['state'] == 'reconciliation_required'
    _, row, restored = append(owner_db, conflict, base)
    assert row['has_conflict']
    with pytest.raises(T.ConfirmationError, match='confirmation_22023'):
        attest(restored)
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s', (row['operation_id'],))
        assert cur.fetchone() == (3,)


def test_out_of_order_read_is_denied_without_replacing_history(owner_db, progression):
    _, row, ready = append(owner_db, progression, progression[3])
    older = replace(ready[3], provenance=replace(ready[3].provenance,
        observed_at=ready[3].provenance.observed_at-timedelta(seconds=1)))
    with closing(connection(ready[0])) as conn:
        repo = V.ObservationRepository(conn)
        with pytest.raises(V.ObservationError, match='observation_22023'):
            repo.record(ready[2], uuid.uuid4(), older)
        assert repo.read(row['operation_id'])['last_observation_id'] == row['last_observation_id']


def test_concurrent_updates_are_fenced_and_grant_no_access(owner_db, progression):
    before = fingerprint(owner_db)
    def submit(_):
        with closing(connection(progression[0])) as conn:
            try:
                V.ObservationRepository(conn).record(progression[2], uuid.uuid4(), progression[3])
                return 'stored'
            except V.ObservationError as error:
                assert str(error) == 'observation_55000'
                return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == ['stale', 'stored']
    assert fingerprint(owner_db) == before


def test_missing_capabilities_cannot_be_fabricated_by_attestor(owner_db, progression):
    before = fingerprint(owner_db)
    pending = replace(progression[3], capabilities=C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED))
    _, _, ready = append(owner_db, progression, pending)
    with pytest.raises(T.ConfirmationError, match='confirmation_22023'):
        attest(ready)  # Synthetic VERIFIED DTO claims capabilities absent in B3.
    assert fingerprint(owner_db) == before


@pytest.mark.parametrize('field', ['tenant_id', 'binding'])
def test_original_request_scope_and_consent_acl_stay_protected(owner_db, progression, field):
    party, request, claim, base, *_ = progression
    doc = V.request_document(request)
    if field == 'binding':
        doc['binding']['environment'] = 'live'
    else:
        doc['tenant_id'] = str(uuid.uuid4())
    with closing(connection(party)) as conn:
        repo = V.ObservationRepository(conn)
        with pytest.raises(V.ObservationError, match='observation_22023'):
            repo._call('SELECT billing_observation_record(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (claim['operation_id'], claim['version'], claim['claim_token'], str(uuid.uuid4()), 'authoritative_lookup',
                 None, request.checkout.opaque_id, base.provenance.observed_at, 'synthetic', 'synthetic', 'pending',
                 Json(V.evidence_document(base)), Json(doc)))
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute('SELECT billing_consent_accept(NULL,NULL,NULL,NULL)')
        conn.rollback()
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute('INSERT INTO billing_trial_consents DEFAULT VALUES')


@pytest.mark.parametrize('section', ['payment_method', 'recurring_authority'])
def test_only_unresolved_subscription_source_can_refine_to_setup(owner_db, evidence, section):
    ready = V.evidence_document(evidence[3]); pending = deepcopy(ready)
    pending['recurring_authority'].update(source=pending['subscription'], kind='unknown', readiness='attached')
    pending['payment_method'].update(source=pending['subscription'], readiness='attached')
    with owner_db.cursor() as cur:
        cur.execute('SELECT billing_confirmation_progresses(%s,%s)', (Json(pending), Json(ready)))
        assert cur.fetchone() == (True,)
        # A positively identified source cannot be replaced by a new setup.
        pending[section]['source'] = 'positive-other-source'
        cur.execute('SELECT billing_confirmation_progresses(%s,%s)', (Json(pending), Json(ready)))
        assert cur.fetchone() == (False,)


@pytest.mark.parametrize('key,value', [('invoice','other'), ('amount_paid','0'), ('currency','JOD'),
    ('confirmed',False), ('coverage',[]), ('purpose','trial_setup')])
def test_settlement_facts_remain_material(owner_db, evidence, key, value):
    old = V.evidence_document(evidence[3])
    old['settlement'] = dict(invoice='invoice_original', amount_paid='59', currency='USD', confirmed=True,
        coverage=[['2026-01-01','2026-02-01']], purpose='recurring_renewal')
    new = deepcopy(old); new['settlement'][key] = value
    with owner_db.cursor() as cur:
        cur.execute('SELECT billing_confirmation_progresses(%s,%s)', (Json(old), Json(new)))
        assert cur.fetchone() == (False,)
