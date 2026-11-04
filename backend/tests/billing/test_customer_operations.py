"""Real SQL/RLS and neutral provider doubles; no external objects or customers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import uuid

import psycopg2
import pytest

from src.ai import db
from src.ai.billing import customer_operations as operations, store
from src.ai.billing.payment_contracts import CustomerSnapshot, FrozenCustomerRequest, ProviderReference, PaymentProviderError, ProviderOperationOutcome as Outcome
from .test_reconciliation_roles import restricted_runtime  # noqa: F401


class Gateway:
    provider='neutral-fixture'
    def __init__(self):
        self.prepared=[];self.sent=[];self.customers={};self.requests={};self.timeout=False;self.recover=False
    def prepare_customer(self,intent):
        self.prepared.append(intent)
        return FrozenCustomerRequest(self.provider,intent.idempotency_key,{'contact':intent.email,'name':intent.company_name,'tenant':intent.tenant_reference},3600)
    def submit_customer(self,request):
        self.sent.append(deepcopy(request))
        if request.idempotency_key in self.requests:
            assert self.requests[request.idempotency_key]==request.payload
        else:
            self.requests[request.idempotency_key]=deepcopy(request.payload)
            self.customers[request.idempotency_key]=CustomerSnapshot(ProviderReference(self.provider,'account-'+uuid.uuid4().hex),request.payload['tenant'])
        if self.timeout:
            self.timeout=False
            raise PaymentProviderError(Outcome.OUTCOME_UNKNOWN)
        return self.customers[request.idempotency_key]
    def get_customer(self,reference,*,tenant_reference):
        return next(c for c in self.customers.values() if c.reference==reference)
    def recover_customer(self,intent):
        return self.customers.get(intent.idempotency_key) if self.recover else None


def resolve(tenant,gateway,email='fixture@example.test',name='Synthetic'):
    with closing(db.app_role_connection(*tenant)) as app,closing(db.billing_setup_connection(*tenant)) as setup:
        return operations.resolve(app,setup,tenant[0],email,name,gateway)


def test_first_create_and_mapped_retry_use_one_operation(tenant,owner_db,restricted_runtime):
    gateway=Gateway();first=resolve(tenant,gateway)
    assert resolve(tenant,gateway,email='changed@example.test',name='Renamed')==first
    assert len(gateway.prepared)==len(gateway.sent)==len(gateway.customers)==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT state,provider_customer_id FROM billing_customer_operations WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchall()==[('succeeded',first)]


def test_unknown_outcome_retries_original_frozen_fields(tenant,restricted_runtime):
    gateway=Gateway();gateway.timeout=True
    with pytest.raises(PaymentProviderError):resolve(tenant,gateway)
    result=resolve(tenant,gateway,email='changed@example.test',name='Renamed')
    assert result and len(gateway.customers)==1 and len(gateway.prepared)==1
    assert len(gateway.sent)==2 and gateway.sent[0]==gateway.sent[1]


def test_positive_recovery_avoids_another_create(tenant,restricted_runtime):
    gateway=Gateway();gateway.timeout=True
    with pytest.raises(PaymentProviderError):resolve(tenant,gateway)
    gateway.recover=True
    assert resolve(tenant,gateway)
    assert len(gateway.sent)==1 and len(gateway.customers)==1


def test_lost_success_commit_reply_keeps_mapping_and_operation(tenant,owner_db,restricted_runtime):
    class LostCommitReply:
        def __init__(self,connection):
            self.connection=connection
            self.commits=0
        def __getattr__(self,name):return getattr(self.connection,name)
        def commit(self):
            self.connection.commit()
            self.commits+=1
            if self.commits==3:
                raise psycopg2.OperationalError('Synthetic lost reply after successful commit')

    gateway=Gateway()
    with closing(db.app_role_connection(*tenant)) as app,closing(db.billing_setup_connection(*tenant)) as setup:
        with pytest.raises(psycopg2.OperationalError,match='lost reply'):
            operations.resolve(app,LostCommitReply(setup),tenant[0],'fixture@example.test','Synthetic',gateway)
    customer=resolve(tenant,gateway)
    assert len(gateway.sent)==len(gateway.customers)==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT state,provider_customer_id,last_error FROM billing_customer_operations WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchall()==[('succeeded',customer,None)]


def test_concurrent_initial_requests_create_one_customer(tenant,restricted_runtime):
    gateway=Gateway()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:resolve(tenant,gateway),range(4)))
    assert len(set(results))==1 and len(gateway.sent)==1 and len(gateway.customers)==1


def test_expired_replay_window_does_not_allow_duplicate(tenant,restricted_runtime,monkeypatch):
    gateway=Gateway();gateway.timeout=True
    with pytest.raises(PaymentProviderError):resolve(tenant,gateway)
    class Future:
        @staticmethod
        def now(tz):return datetime.now(tz)+timedelta(days=2)
    monkeypatch.setattr(operations,'datetime',Future)
    with pytest.raises(operations.CustomerOperationError,match='customer_creation_reconciling'):resolve(tenant,gateway)
    assert len(gateway.sent)==len(gateway.customers)==1
    gateway.recover=True
    assert resolve(tenant,gateway)
    assert len(gateway.sent)==1


def test_customer_mapping_mismatch_cannot_replace_identity(tenant,owner_db,restricted_runtime):
    gateway=Gateway();original=resolve(tenant,gateway)
    with pytest.raises(ValueError,match='mapping conflict'):store.save_customer(owner_db,tenant[0],'replacement-forbidden')
    assert store.customer_id(owner_db,tenant[0])==original
    record=next(iter(gateway.customers.values()))
    gateway.customers[next(iter(gateway.customers))]=CustomerSnapshot(record.reference,str(uuid.uuid4()))
    with pytest.raises(operations.CustomerOperationError,match='customer_identity_conflict'):resolve(tenant,gateway)
    assert len(gateway.sent)==1


def test_legacy_unknown_operation_never_invents_payload_or_key(tenant,owner_db,restricted_runtime):
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO billing_customer_operations(operation_id,tenant_id,provider,idempotency_key,replay_window_seconds,state) VALUES(%s,%s,%s,%s,1,'legacy_unresolved')",
                    (str(uuid.uuid4()),tenant[0],Gateway.provider,'original-legacy-key'))
    gateway=Gateway()
    with pytest.raises(operations.CustomerOperationError,match='customer_creation_reconciling'):resolve(tenant,gateway)
    assert not gateway.prepared and not gateway.sent and not gateway.customers


def test_recovered_legacy_customer_is_mapped_without_create(tenant,owner_db,restricted_runtime):
    key='original-legacy-key'
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO billing_customer_operations(operation_id,tenant_id,provider,idempotency_key,replay_window_seconds,state) VALUES(%s,%s,%s,%s,1,'legacy_unresolved')",
                    (str(uuid.uuid4()),tenant[0],Gateway.provider,key))
    gateway=Gateway();gateway.recover=True
    gateway.customers[key]=CustomerSnapshot(ProviderReference(gateway.provider,'previously-created'),tenant[0])
    assert resolve(tenant,gateway)=='previously-created'
    assert not gateway.prepared and not gateway.sent


def test_definitive_rejection_allows_new_durable_operation(tenant,owner_db,restricted_runtime):
    gateway=Gateway()
    def rejected(request):raise PaymentProviderError(Outcome.REJECTED)
    gateway.submit_customer=rejected
    with pytest.raises(PaymentProviderError):resolve(tenant,gateway)
    del gateway.submit_customer
    assert resolve(tenant,gateway,name='Corrected')
    assert len(gateway.prepared)==2
    assert gateway.prepared[0].idempotency_key!=gateway.prepared[1].idempotency_key
    assert len(gateway.customers)==1


def test_customer_operation_force_rls_and_frozen_columns(tenant,owner_db,restricted_runtime):
    gateway=Gateway();gateway.timeout=True
    with pytest.raises(PaymentProviderError):resolve(tenant,gateway)
    with closing(db.app_role_connection(*tenant)) as app,app.cursor() as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute('SELECT * FROM billing_customer_operations')
    with closing(db.billing_setup_connection(*tenant)) as setup,setup.cursor() as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute("UPDATE billing_customer_operations SET request_params='{}' WHERE tenant_id=%s",(tenant[0],))
    with closing(db.billing_setup_connection(str(uuid.uuid4()),tenant[1])) as other,other.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_customer_operations');assert cur.fetchone()[0]==0
    with owner_db.cursor() as cur:
        cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_customer_operations'::regclass")
        assert cur.fetchone()==(True,True)
        with pytest.raises(psycopg2.errors.InvalidParameterValue):cur.execute("UPDATE billing_customer_operations SET idempotency_key='forged' WHERE tenant_id=%s",(tenant[0],))
