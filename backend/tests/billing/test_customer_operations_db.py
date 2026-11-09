"""Real restricted-password PG17 proofs with offline provider doubles only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta
from threading import Event
from types import SimpleNamespace
import time
import uuid

import psycopg2
import pytest

from src.ai import db
from src.ai.billing import customer_operations as operations, payment_bindings, stripe_api
from src.ai.billing.payment_contracts import (
    CapabilityState, CustomerIntent, CustomerRecoveryResult, CustomerRecoveryStatus,
    CustomerSnapshot, PaymentProviderError, ProviderOperationOutcome as Outcome, ProviderReference,
)
from .test_payment_bindings_db import parties  # noqa: F401 - existing isolated synthetic fixture
from .test_reconciliation_roles import restricted_runtime  # noqa: F401
from .test_customer_contracts import Transport
from src.ai.billing.stripe_gateway import StripeDurableCustomerGateway


class Gateway:
    def __init__(self, binding):
        self.binding = binding
        self.encoder = StripeDurableCustomerGateway(binding, Transport(binding))
        self.sent = []
        self.customers = {}
        self.error = None
        self.recovery = CustomerRecoveryStatus.INCONCLUSIVE
        self.pause = None
        self.pause_before = None
        self.late_conflict = False

    def prepare_customer(self, intent): return self.encoder.prepare_customer(intent)

    def submit_customer(self, request, *, deadline, authorize):
        if self.pause_before:
            entered, resume = self.pause_before
            entered.set(); assert resume.wait(10)
        authorize()
        self.sent.append(request)
        if self.error is Outcome.REJECTED:
            raise PaymentProviderError(self.error)  # Definitive no-create rejection in this double.
        snapshot = self.customers.setdefault(request.idempotency_key, CustomerSnapshot(
            ProviderReference(self.binding.provider,'cus_'+request.operation_id,binding=self.binding),
            request.tenant_id,request.operation_id,'create_response','synthetic-provider-double'))
        if self.pause:
            entered, resume = self.pause
            entered.set(); assert resume.wait(10)
        if self.error: raise PaymentProviderError(self.error)
        if self.late_conflict:
            snapshot=replace(snapshot,reference=ProviderReference(self.binding.provider,'conflicting-late-customer',binding=self.binding))
        return snapshot

    def recover_customer(self, request):
        snapshot = self.customers.get(request.idempotency_key) if self.recovery is CustomerRecoveryStatus.MATCH else None
        return CustomerRecoveryResult(self.recovery,self.binding,request.tenant_id,request.operation_id,snapshot,
            'synthetic-operation-wide-evidence' if self.recovery is CustomerRecoveryStatus.VERIFIED_NON_CREATION else None)


@pytest.fixture
def scenario(parties):
    party = parties[0]
    with closing(db.billing_setup_connection(*party)) as conn:
        binding = payment_bindings.selected(conn)
    intent = CustomerIntent(party[0],str(uuid.uuid4()),str(uuid.uuid4()),binding,'customer@example.test','Synthetic')
    return party,intent,Gateway(binding)


def repository(party):
    return closing(db.billing_setup_connection(*party))


def run(scenario, *, intent=None, wrapper=None):
    party, original, gateway = scenario
    with repository(party) as conn:
        repo = operations.CustomerRepository(conn)
        return operations.resolve(wrapper(repo) if wrapper else repo,intent or original,lambda binding: gateway)


def read(scenario):
    with repository(scenario[0]) as conn:
        return operations.CustomerRepository(conn).read(scenario[1].operation_id)


def expire(owner_db, scenario):
    # Fixture-only clock advancement, not a production recovery mechanism.
    with owner_db.cursor() as cur:
        cur.execute('BEGIN')
        cur.execute("SELECT set_config('app.current_tenant',%s,true),set_config('app.current_tenant_id',%s,true)",
                    (scenario[0][0],scenario[0][0]))
        cur.execute("SELECT set_config('app.current_user_id',%s,true)", (scenario[0][1],))
        cur.execute('SET LOCAL ROLE ceopro_trial_issuer')
        cur.execute("UPDATE billing_customer_operations SET claim_until=clock_timestamp()-interval '1 second',version=version+1 WHERE operation_id=%s",
                    (scenario[1].operation_id,))
        assert cur.rowcount == 1, 'Fixture clock must update exactly its own operation'
        cur.execute('COMMIT')


def pending(scenario, dispatch=False):
    party,intent,gateway=scenario
    with repository(party) as conn:
        repo=operations.CustomerRepository(conn)
        row=repo.begin(intent,gateway.prepare_customer(intent)); token=uuid.uuid4()
        row=repo.command(row,'claim',token)
        if dispatch: row=repo.command(row,'dispatch',token)
        return row,token


def fingerprint(owner_db):
    tables=('billing_customers','billing_subscriptions','billing_trials','tenant_plan_assignments',
            'tenant_credit_balances','usage_ledger','tenant_entitlement_overrides')
    with owner_db.cursor() as cur:
        result=[]
        for table in tables:
            cur.execute(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text FROM {table} t")
            result.append(cur.fetchone()[0])
        return result


def test_success_replay_is_atomic_scoped_and_has_no_billing_effects(owner_db,scenario):
    before=fingerprint(owner_db)
    first=run(scenario)
    assert run(scenario)==first
    assert len(scenario[2].sent)==1
    row=read(scenario)
    assert row['state']=='succeeded' and row['reference_id'] and row['confirmation']['binding']==asdict(scenario[1].binding)
    assert fingerprint(owner_db)==before


def test_pending_request_is_frozen_and_changed_logical_replay_is_denied(owner_db,scenario):
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    with pytest.raises(operations.CustomerOperationError,match='request_conflict'):
        run(scenario,intent=replace(scenario[1],email='changed@example.test'))
    scenario[2].error=None
    scenario[2].encoder.transport.api_version='new-encoder-config'
    with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(scenario)
    assert len(scenario[2].customers)==1
    assert len(scenario[2].sent)==1
    assert read(scenario)['transport_request']==scenario[2].sent[0].transport.canonical.decode()


def test_provider_success_lost_response_and_positive_recovery(owner_db,scenario):
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    scenario[2].error=None;scenario[2].recovery=CustomerRecoveryStatus.MATCH
    run(scenario)
    assert len(scenario[2].sent)==1 and read(scenario)['state']=='succeeded'


def test_db_confirmation_failure_then_lost_commit_reply_recovers(owner_db,scenario):
    class Failure:
        def __init__(self,repo):self.repo=repo
        def __getattr__(self,name):return getattr(self.repo,name)
        def command(self,row,action,token,payload=None):
            if action=='confirm':raise RuntimeError('synthetic persistence failure')
            return self.repo.command(row,action,token,payload)
    with pytest.raises(RuntimeError):run(scenario,wrapper=Failure)
    assert read(scenario)['state']=='submitted'
    expire(owner_db,scenario);scenario[2].recovery=CustomerRecoveryStatus.MATCH
    class LostReply(Failure):
        def command(self,row,action,token,payload=None):
            result=self.repo.command(row,action,token,payload)
            if action=='confirm':raise RuntimeError('synthetic lost commit reply')
            return result
    with pytest.raises(RuntimeError):run(scenario,wrapper=LostReply)
    assert read(scenario)['state']=='succeeded'
    run(scenario)
    assert len(scenario[2].sent)==1


@pytest.mark.parametrize('dispatch',[False,True])
def test_crash_before_dispatch_and_after_marker_preserves_original_operation(owner_db,scenario,dispatch):
    pending(scenario,dispatch)
    assert not scenario[2].sent
    expire(owner_db,scenario)
    if dispatch:
        with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(scenario)
        assert not scenario[2].sent and read(scenario)['dispatch_count']==1
    else:
        run(scenario)
        assert len(scenario[2].sent)==1


def test_later_retry_rejection_cannot_erase_unknown_outcome(scenario):
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    # Preserve the existing SQL invariant for previously submitted legacy replays;
    # the new coordinator no longer dispatches these replays automatically.
    with repository(scenario[0]) as conn:
        repo=operations.CustomerRepository(conn);row=repo.read(scenario[1].operation_id);token=uuid.uuid4()
        row=repo.command(row,'claim',token);row=repo.command(row,'dispatch',token)
        repo.command(row,'fail',token,{'code':'rejected'})
    assert read(scenario)['state']=='unknown' and read(scenario)['dispatch_count']==2
    assert len(scenario[2].sent)==1


@pytest.mark.parametrize('outcome,state',[(Outcome.REJECTED,'rejected'),(Outcome.UNAVAILABLE,'unknown'),
    (Outcome.NOT_FOUND,'unknown'),(Outcome.OUTCOME_UNKNOWN,'unknown')])
def test_first_dispatch_error_categories_are_distinct(scenario,outcome,state):
    scenario[2].error=outcome
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    assert read(scenario)['state']==state
    if outcome is Outcome.REJECTED: assert not scenario[2].customers


def test_unknown_replay_guarantee_does_not_authorize_new_creation(owner_db,scenario):
    scenario[2].encoder.transport.replay_window_seconds=0
    with pytest.raises(operations.CustomerOperationError,match='unsupported_capability'):run(scenario)
    assert not scenario[2].sent and read(scenario)['state']=='reconciliation_required'


@pytest.mark.parametrize('recovery',[CustomerRecoveryStatus.CONFLICT,None,CustomerRecoveryStatus.VERIFIED_NON_CREATION])
def test_conflicting_missing_and_operation_wide_recovery(owner_db,scenario,recovery):
    pending(scenario,True);expire(owner_db,scenario)
    if recovery is None:scenario[2].recover_customer=None
    else:scenario[2].recovery=recovery
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    assert read(scenario)['state']==('rejected' if recovery is CustomerRecoveryStatus.VERIFIED_NON_CREATION else 'reconciliation_required')
    assert not scenario[2].sent


@pytest.mark.parametrize('conflicting_response',[False,True])
def test_concurrent_workers_and_paused_stale_late_response(owner_db,scenario,conflicting_response):
    entered,resume=Event(),Event();scenario[2].pause=(entered,resume)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(run,scenario)
        assert entered.wait(5)
        with pytest.raises(psycopg2.Error):run(scenario)
        expire(owner_db,scenario)
        scenario[2].recovery=CustomerRecoveryStatus.MATCH
        result=run(scenario)
        scenario[2].late_conflict=conflicting_response
        resume.set()
        with pytest.raises(psycopg2.Error):future.result(timeout=5)
    assert run(scenario)==result and len(scenario[2].sent)==1


def test_paused_before_dispatch_is_fenced_after_claim_recovery(owner_db,scenario):
    entered,resume=Event(),Event();scenario[2].pause_before=(entered,resume)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(run,scenario)
        assert entered.wait(5)
        expire(owner_db,scenario)
        scenario[2].pause_before=None
        with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(scenario)
        resume.set()
        with pytest.raises(psycopg2.Error):future.result(timeout=5)
    assert read(scenario)['state']=='reconciliation_required' and not scenario[2].sent


def test_only_unsubmitted_can_cancel_and_terminal_result_is_fenced(owner_db,scenario):
    pending(scenario);expire(owner_db,scenario)
    with repository(scenario[0]) as conn:
        assert operations.cancel_unsubmitted(operations.CustomerRepository(conn),scenario[1].operation_id)['state']=='cancelled'
    with pytest.raises(operations.CustomerOperationError):run(scenario)


def test_real_password_rls_and_command_privileges(owner_db,parties,scenario):
    pending(scenario)
    with repository(parties[1]) as conn:
        repo=operations.CustomerRepository(conn)
        assert repo.read(scenario[1].operation_id) is None
        with conn.cursor() as cur:
            cur.execute('SELECT session_user,current_user');assert cur.fetchone()==('ceopro_billing_setup','ceopro_billing_setup')
            for statement in ['SET ROLE ceopro_trial_issuer','CREATE TABLE forbidden_customer(id int)',
                              "UPDATE billing_customer_operations SET state='succeeded'"]:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute(statement)
                conn.rollback()
    with pytest.raises(ValueError):operations.CustomerRepository(owner_db)
    with owner_db.cursor() as cur:
        cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_customer_operations'::regclass")
        assert cur.fetchone()==(True,True)
        cur.execute("SELECT r.rolname,p.prosecdef,p.proconfig,has_function_privilege('ceopro_app',p.oid,'EXECUTE'),has_function_privilege('ceopro_billing_webhook',p.oid,'EXECUTE') FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.proname IN ('billing_customer_begin','billing_customer_command','billing_customer_operation')")
        rows=cur.fetchall();assert len(rows)==3
        assert all(owner=='ceopro_trial_issuer' and sec and 'search_path=pg_catalog, public, pg_temp' in config and not app and not webhook for owner,sec,config,app,webhook in rows)


def test_disabled_selection_recovers_original_binding_and_rejects_foreign_evidence(owner_db,scenario):
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    with owner_db.cursor() as cur:cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE binding_id=%s',(scenario[1].binding.binding_id,))
    scenario[2].error=None;scenario[2].recovery=CustomerRecoveryStatus.MATCH
    assert run(scenario).binding==scenario[1].binding
    with pytest.raises(operations.CustomerOperationError):run(scenario,intent=replace(scenario[1],tenant_id=str(uuid.uuid4())))


def test_confirmation_and_mapping_rollback_together_on_sql_failure(owner_db,scenario):
    row,token=pending(scenario,True)
    request=operations.frozen_from(row)
    snapshot=scenario[2].submit_customer(request,deadline=None,authorize=lambda:None)
    with repository(scenario[0]) as conn:
        repo=operations.CustomerRepository(conn)
        payload=operations._evidence(request,snapshot)
        payload['binding']['merchant_account_id']='wrong'
        with pytest.raises(psycopg2.Error):repo.command(row,'confirm',token,payload)
    assert read(scenario)['state']=='submitted'
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_customer_references WHERE tenant_id=%s',(scenario[0][0],))
        assert cur.fetchone()==(0,)


def test_real_expired_replay_deadline_blocks_after_empty_recovery(scenario):
    scenario[2].encoder.transport.replay_window_seconds=4
    scenario[2].encoder.transport.timeout=1
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    time.sleep(4.2)  # One bounded actual database-clock expiry; no policy bypass.
    with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(scenario)
    assert len(scenario[2].sent)==1 and read(scenario)['state']=='reconciliation_required'


def test_same_tenant_competing_request_and_cross_binding_replay(owner_db,scenario):
    pending(scenario)
    other=replace(scenario[1],operation_id=str(uuid.uuid4()),request_identity='competing')
    with pytest.raises(psycopg2.errors.UniqueViolation):run(scenario,intent=other)
    foreign=replace(scenario[1].binding,merchant_account_id='another-account',binding_id='another-binding')
    with pytest.raises(operations.CustomerOperationError):run(scenario,intent=replace(scenario[1],binding=foreign))
    assert not scenario[2].sent


def test_existing_legacy_customer_is_not_adopted_or_replaced(owner_db,scenario):
    with owner_db.cursor() as cur:
        cur.execute('INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,%s)',
                    (scenario[0][0],'legacy_'+uuid.uuid4().hex))
    with pytest.raises(psycopg2.errors.InvalidParameterValue,match='provenance'):run(scenario)
    assert not scenario[2].sent


def test_successful_confirmation_rolls_back_mapping_if_update_fails(owner_db,scenario):
    row,token=pending(scenario,True);request=operations.frozen_from(row)
    snapshot=scenario[2].submit_customer(request,deadline=None,authorize=lambda:None)
    with owner_db.cursor() as cur:
        cur.execute("CREATE FUNCTION customer_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.state='succeeded' THEN RAISE EXCEPTION 'synthetic confirmation failure'; END IF; RETURN NEW; END $$")
        cur.execute('CREATE TRIGGER customer_test_failure BEFORE UPDATE ON billing_customer_operations FOR EACH ROW EXECUTE FUNCTION customer_test_failure()')
    try:
        with repository(scenario[0]) as conn,pytest.raises(psycopg2.Error):
            operations.CustomerRepository(conn).command(row,'confirm',token,operations._evidence(request,snapshot))
    finally:
        with owner_db.cursor() as cur:
            cur.execute('DROP TRIGGER customer_test_failure ON billing_customer_operations')
            cur.execute('DROP FUNCTION customer_test_failure()')
    assert read(scenario)['state']=='submitted'
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_customer_references WHERE tenant_id=%s',(scenario[0][0],))
        assert cur.fetchone()==(0,)


def test_terminal_and_stale_claim_mutations_are_denied(owner_db,scenario):
    row,token=pending(scenario);expire(owner_db,scenario)
    scenario[2].recovery=CustomerRecoveryStatus.INCONCLUSIVE
    run(scenario);before=read(scenario)
    with repository(scenario[0]) as conn:
        repo=operations.CustomerRepository(conn)
        with pytest.raises(psycopg2.Error):repo.command(row,'fail',token,{'code':'rejected'})
        with pytest.raises(psycopg2.Error):repo.command(before,'claim',uuid.uuid4())
    assert {k:v for k,v in read(scenario).items() if k!='database_now'} == {k:v for k,v in before.items() if k!='database_now'}


def test_revoked_principal_cannot_resume_or_read(owner_db,scenario):
    pending(scenario)
    with owner_db.cursor() as cur:
        cur.execute('UPDATE tenant_users SET removed_at=clock_timestamp() WHERE tenant_id=%s AND user_id=%s',scenario[0])
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):run(scenario)
    assert not scenario[2].sent


def test_malformed_recovery_result_requires_reconciliation(owner_db,scenario):
    pending(scenario,True);expire(owner_db,scenario)
    scenario[2].recover_customer=lambda request:None
    with pytest.raises(operations.CustomerOperationError,match='recovery_malformed'):run(scenario)
    assert not scenario[2].sent and read(scenario)['state']=='reconciliation_required'


def test_null_version_and_null_claim_cannot_bypass_fencing(scenario):
    row,token=pending(scenario)
    with repository(scenario[0]) as conn:
        repo=operations.CustomerRepository(conn)
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            repo.command(dict(row,version=None),'cancel',token)
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            repo._call('SELECT public.billing_customer_command(%s,%s,%s,%s,%s)',
                       (row['operation_id'],row['version'],'cancel',None,'{}'))
    assert read(scenario)['state']=='prepared' and not scenario[2].sent


def test_unknown_provider_outcome_never_automatically_creates_a_second_customer(scenario):
    scenario[2].error=Outcome.OUTCOME_UNKNOWN
    with pytest.raises(operations.CustomerOperationError):run(scenario)
    before=read(scenario)
    # Provider search is empty even though the first call created a Customer.
    scenario[2].error=Outcome.REJECTED
    for _ in range(2):
        with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(scenario)
    after=read(scenario)
    assert len(scenario[2].sent)==len(scenario[2].customers)==1
    assert after['state']=='reconciliation_required' and after['dispatch_count']==1
    for key in ('binding','idempotency_key','transport_request','logical_request','replay_deadline'):
        assert after[key]==before[key]


@pytest.mark.parametrize('legacy_replay', [False, True])
def test_authorized_worker_paused_past_deadline_sends_nothing_and_can_reconcile(
        owner_db,scenario,monkeypatch,legacy_replay):
    party,intent,_=scenario
    transport=Transport(intent.binding);gateway=StripeDurableCustomerGateway(intent.binding,transport)
    bound=(party,intent,gateway)
    entered,resume=Event(),Event()
    clock=SimpleNamespace(now=datetime.now(timezone.utc))
    monkeypatch.setattr(stripe_api,'datetime',SimpleNamespace(
        now=lambda tz:clock.now,fromisoformat=datetime.fromisoformat))
    if legacy_replay:
        # Simulate an authorization still allowed by the unchanged historical SQL.
        row,token=pending(scenario,True)
        with repository(party) as conn:
            row=operations.CustomerRepository(conn).command(row,'dispatch',token)
        assert row['dispatch_count']==2
    class PausedAuthorization:
        def __init__(self,repo):self.repo=repo
        def __getattr__(self,name):return getattr(self.repo,name)
        def command(self,row,action,token,payload=None):
            result=self.repo.command(row,action,token,payload)
            if action=='authorize':
                clock.deadline=datetime.fromisoformat(result['replay_deadline'])
                entered.set();assert resume.wait(10)
            return result
    def worker():
        if not legacy_replay:return run(bound,wrapper=PausedAuthorization)
        with repository(party) as conn:
            repo=PausedAuthorization(operations.CustomerRepository(conn))
            return gateway.submit_customer(operations.frozen_from(row),
                deadline=datetime.fromisoformat(row['replay_deadline']),
                authorize=lambda:repo.command(row,'authorize',token))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(worker);assert entered.wait(5)
        before=read(bound)
        clock.now=clock.deadline+timedelta(seconds=1)
        resume.set()
        with pytest.raises((operations.CustomerOperationError,PaymentProviderError)):
            future.result(timeout=5)
    assert not any(isinstance(call,tuple) for call in transport.calls)
    if legacy_replay:expire(owner_db,bound)
    with pytest.raises(operations.CustomerOperationError,match='reconciliation_required'):run(bound)
    after=read(bound)
    assert after['state']=='reconciliation_required'
    for key in ('binding','idempotency_key','transport_request','logical_request','dispatch_count'):
        assert after[key]==before[key]
