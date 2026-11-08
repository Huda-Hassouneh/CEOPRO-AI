"""New native fences; all policies/provider/consent fixtures are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
import time
import os
import uuid
import pytest
import psycopg2
from psycopg2.extras import Json
from src.ai.billing import recurring_consent as R
from .test_recurring_consent_db import (parties, policy, presentation, associated_context,
    service, accept, invalidate, associate, fingerprint, customer_scenario, restricted_runtime, wait_blocked)
from .test_trial_confirmation_db import evidence, attest, confirm


def test_associated_withdrawal_is_immutable_and_blocks_exact_reassociation(owner_db,associated_context):
    party,r,p,a,operation=associated_context
    bridge=associate(party,a,operation);before=fingerprint(owner_db)
    i=invalidate(party,p,R.ConsentState.WITHDRAWN)
    assert invalidate(party,p,R.ConsentState.WITHDRAWN)==i
    with pytest.raises(R.ConsentError,match='consent_22023'): associate(party,a,operation)
    with closing(service(party)) as c:
        value=R.ConsentRepository(c).read(r['attempt_id'],p['presentation_id']).unpack()
        assert value['invalidation']['reason']=='withdrawn' and value['acceptance']['acceptance_id']==a['acceptance_id']
        assert 'challenge_digest' not in value['presentation'] and 'challenge' not in value['presentation']
    assert fingerprint(owner_db)==before
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM billing_consent_associations WHERE acceptance_id=%s',(a['acceptance_id'],));assert q.fetchone()==(1,)
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            q.execute('DELETE FROM billing_consent_invalidations WHERE presentation_id=%s',(p['presentation_id'],))


def test_withdrawal_read_denies_other_actor_or_tenant(owner_db,presentation,parties):
    party,r,p=presentation
    for other in (parties[1],(party[0],parties[1][1])):
        with closing(service(other)) as c:
            with pytest.raises(R.ConsentError,match='consent_42501'):
                R.ConsentRepository(c).read(r['attempt_id'],p['presentation_id'])


def test_withdrawal_wins_over_late_acceptance(owner_db,presentation):
    party,r,p=presentation
    with closing(service(party)) as first, closing(service(party)) as second:
        with second.cursor() as q:q.execute('SELECT pg_backend_pid()');pid=q.fetchone()[0]
        with first.cursor() as q:q.execute('SELECT billing_consent_invalidate(%s,%s)',(p['presentation_id'],'withdrawn'))
        def later():
            return R.ConsentRepository(second).accept(R.PresentationIdentity(uuid.UUID(p['presentation_id']),p['terms_digest']),p['challenge'])
        with ThreadPoolExecutor() as pool:
            future=pool.submit(later)
            try: wait_blocked(owner_db,pid)
            finally: first.commit()
            with pytest.raises(R.ConsentError,match='consent_22023'):future.result(timeout=8)


def test_acceptance_first_then_withdrawal_is_preserved_and_invalidated(owner_db,presentation):
    party,r,p=presentation
    with closing(service(party)) as first, closing(service(party)) as second:
        with second.cursor() as q:q.execute('SELECT pg_backend_pid()');pid=q.fetchone()[0]
        with first.cursor() as q:q.execute('SELECT billing_consent_accept(%s,%s,%s,%s)',(str(uuid.uuid4()),p['presentation_id'],p['challenge'],p['terms_digest']))
        with ThreadPoolExecutor() as pool:
            future=pool.submit(lambda:R.ConsentRepository(second).invalidate(uuid.UUID(p['presentation_id']),R.ConsentState.WITHDRAWN).unpack())
            try: wait_blocked(owner_db,pid)
            finally: first.commit()
            assert future.result(timeout=8)['reason']=='withdrawn'
    with closing(service(party)) as c:
        value=R.ConsentRepository(c).read(r['attempt_id'],p['presentation_id']).unpack()
        assert value['acceptance'] and value['invalidation']


@pytest.fixture
def a1_evidence(owner_db,evidence):
    # Attach immutable synthetic A1 provenance to the existing B4 fixture. This
    # installer-only seed tests consumption, not genuine customer acceptance.
    party,request,claim,base,verified,cid=evidence
    pid=policy(owner_db);presentation_id=str(uuid.uuid4())
    with owner_db.cursor() as q:
        q.execute('SELECT to_jsonb(r),accepted_at FROM billing_trial_checkouts r JOIN billing_trial_consents c ON c.consent_id=%s WHERE attempt_id=%s',(cid,str(request.reservation_id)))
        r,accepted_at=q.fetchone()
        q.execute("INSERT INTO billing_consent_presentations(presentation_id,tenant_id,binding_id,attempt_id,actor_id,policy_id,quantity,approved_terms,terms_digest,status,challenge_digest,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s,'presented',%s,%s-interval '1 second',%s+interval '1 hour')",(presentation_id,party[0],r['binding_id'],r['attempt_id'],party[1],pid,Json(r['approved_terms']),claim['terms_digest'] if 'terms_digest' in claim else request.approved_terms_digest,'sha256:'+uuid.uuid4().hex*2,accepted_at,accepted_at))
        q.execute('INSERT INTO billing_consent_acceptances(acceptance_id,presentation_id,tenant_id,binding_id,attempt_id,actor_id,accepted_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',(cid,presentation_id,party[0],r['binding_id'],r['attempt_id'],party[1],accepted_at))
    return evidence,dict(presentation_id=presentation_id)


def test_withdrawn_a1_cannot_be_newly_attested(owner_db,a1_evidence):
    e,p=a1_evidence;before=fingerprint(owner_db)
    invalidate(e[0],p,R.ConsentState.WITHDRAWN)
    with pytest.raises(Exception,match='confirmation_22023'):attest(e)
    assert fingerprint(owner_db)==before


def test_withdrawal_after_attestation_prevents_confirmation_and_rolls_back_rights(owner_db,a1_evidence):
    e,p=a1_evidence;a=attest(e);before=fingerprint(owner_db)
    invalidate(e[0],p,R.ConsentState.WITHDRAWN)
    with pytest.raises(Exception,match='confirmation_22023'):confirm(e,a)
    assert fingerprint(owner_db)==before


def test_confirmation_first_requires_cancellation_not_historical_invalidation(owner_db,a1_evidence):
    e,p=a1_evidence;a=attest(e);result=confirm(e,a)
    with pytest.raises(R.ConsentError,match='consent_55000'):invalidate(e[0],p,R.ConsentState.WITHDRAWN)
    assert confirm(e,a)==result
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM billing_consent_invalidations WHERE presentation_id=%s',(p['presentation_id'],));assert q.fetchone()==(0,)


def test_busy_attestation_fence_is_nowait_and_recoverable(a1_evidence):
    e,p=a1_evidence
    with closing(psycopg2.connect(os.environ['BILLING_TEST_DATABASE_URL'])) as c:
        with c.cursor() as q:q.execute('SELECT attempt_id FROM billing_trial_checkouts WHERE attempt_id=%s FOR UPDATE',(str(e[1].reservation_id),))
        with pytest.raises(Exception,match='confirmation_55P03'):attest(e)
        c.rollback()
    assert attest(e)['attestation_id']
