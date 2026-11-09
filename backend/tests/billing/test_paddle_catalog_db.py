"""Real isolated PostgreSQL journal, authority, ACL and concurrency proof."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import closing
from types import SimpleNamespace
import os,threading,uuid
import psycopg2
from psycopg2.extras import Json
import pytest
from src.ai.billing import paddle_catalog as P
from src.ai.billing import payment_contracts as C
from .test_paddle_catalog import Transport,MANIFEST


class NativeTransport(Transport):
    def request(self,method,path,body=None,*,params=None):
        if method=='POST':
            from psycopg2.extensions import TRANSACTION_STATUS_IDLE
            assert self.store.conn.get_transaction_status()==TRANSACTION_STATUS_IDLE
            with self.store.conn.cursor() as q:
                q.execute('SELECT state,request FROM billing_catalog_operations WHERE binding_id=%s',(self.binding.binding_id,))
                self.store.data={str(i):dict(state=state,request=request) for i,(state,request) in enumerate(q.fetchall())}
            self.store.conn.commit()
        return super().request(method,path,body,params=params)


@pytest.fixture
def catalog(owner_db, platform_owner_context):
    # This file runs only on the separately prepared disposable proof database.
    dsn=os.environ['BILLING_TEST_DATABASE_URL']
    with owner_db.cursor() as q:
        party=platform_owner_context
        key='catalog_'+uuid.uuid4().hex
        q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,provenance) VALUES(%s,'paddle','test',%s,'SYNTHETIC catalog test')",(key,key))
        q.execute('SELECT current_database()');database=q.fetchone()[0]
        q.execute("SELECT price_id::text FROM billing_plan_prices WHERE plan_key='growth' AND retired_at IS NULL")
        price_ids=[row[0] for row in q.fetchall()]
    conn=psycopg2.connect(dsn)
    manifest=dict(deepcopy(MANIFEST),database=database,binding_id=key,merchant_account_id=key,price_ids=price_ids)
    repo=P.CatalogRepository(conn,str(party[1]),str(party[0]),manifest)
    rows,expected=repo.snapshot()
    assert rows and all(row['plan_key']=='growth' for row in rows)
    transport=NativeTransport(repo);transport.binding=repo.binding
    transport.verify_namespace=lambda:None
    adapter=P.CatalogAdapter(repo.binding,transport)
    try:yield SimpleNamespace(repo=repo,transport=transport,adapter=adapter,expected=expected,owner=str(party[1]),tenant=str(party[0]),dsn=dsn,rows=rows)
    finally:conn.close()


def sync(s):return P.synchronize(s.repo,s.adapter,expected=s.expected,apply=True)


def test_real_durable_create_mapping_exact_repeat_and_history(catalog,owner_db):
    # Other cases retain consent/audit history in this same disposable cluster.
    with owner_db.cursor() as q:
        q.execute('SELECT (SELECT count(*) FROM billing_subscriptions),(SELECT count(*) FROM billing_consent_acceptances)')
        before=q.fetchone()
    s=catalog;expected=len(s.rows)+1;sync(s);assert len(s.transport.posts)==expected
    assert len(sync(s)['actions'])==expected and len(s.transport.posts)==expected
    with owner_db.cursor() as q:
        q.execute('SELECT state,provider_object_id FROM billing_catalog_operations WHERE binding_id=%s ORDER BY entity_kind',(s.repo.binding.binding_id,));rows=q.fetchall()
        assert len(rows)==expected and all(state=='succeeded' and identifier for state,identifier in rows)
        q.execute('SELECT count(*) FROM billing_price_references WHERE binding_id=%s',(s.repo.binding.binding_id,));assert q.fetchone()==(len(s.rows),)
        q.execute('SELECT (SELECT count(*) FROM billing_subscriptions),(SELECT count(*) FROM billing_consent_acceptances)')
        assert q.fetchone()==before
    for statement in ('DELETE FROM billing_catalog_operations WHERE binding_id=%s',"UPDATE billing_catalog_operations SET request='{}' WHERE binding_id=%s"):
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            with s.repo.conn.cursor() as q:q.execute(statement,(s.repo.binding.binding_id,))
        s.repo.conn.rollback()


def test_real_lost_response_empty_recovery_and_late_discovery(catalog):
    s=catalog;s.transport.lost='product'
    with pytest.raises(TimeoutError):sync(s)
    s.transport.hide=True
    with pytest.raises(P.CatalogBlocked,match='GET recovery only'):sync(s)
    assert len(s.transport.posts)==1
    s.transport.hide=False;sync(s);assert len(s.transport.posts)==len(s.rows)+1


def test_tenant_owner_is_not_platform_owner_and_revocation_prevents_send(catalog,owner_db):
    s=catalog
    foreign=P.CatalogRepository(s.repo.conn,s.owner,str(uuid.uuid4()),s.repo.manifest)
    with pytest.raises(P.CatalogBlocked,match='Platform Owner'):foreign.snapshot()
    s.repo.conn.rollback()
    def demote():
        with owner_db.cursor() as q:q.execute("UPDATE keel_platform_members SET role_key='admin' WHERE user_id=%s",(s.owner,))
    s.transport.during_read=demote
    try:
        with pytest.raises(P.CatalogBlocked,match='Platform Owner'):sync(s)
        assert not s.transport.posts
    finally:
        with owner_db.cursor() as q:q.execute("UPDATE keel_platform_members SET role_key='owner' WHERE user_id=%s",(s.owner,))


def test_real_claim_concurrency_has_one_winner(catalog):
    s=catalog;request={'name':'SYNTHETIC'}
    op=s.repo.prepare('product','claim-test',request)
    gate=threading.Barrier(2)
    def claim():
        with closing(psycopg2.connect(s.dsn)) as conn:
            repo=P.CatalogRepository(conn,s.owner,s.tenant,s.repo.manifest);gate.wait()
            try:repo.claim(op,s.expected);return 'sent'
            except P.CatalogBlocked:conn.rollback();return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:claim(),range(2)))
    assert sorted(results)==['blocked','sent']


def test_real_publisher_lock_is_explicit_recoverable(catalog):
    s=catalog
    with closing(psycopg2.connect(s.dsn)) as other:
        repo=P.CatalogRepository(other,s.owner,s.tenant,s.repo.manifest)
        with s.repo.lock():
            with pytest.raises(P.CatalogBlocked,match='busy'):
                with repo.lock():pytest.fail('Concurrent publisher entered')
        other.rollback()
        with repo.lock():pass


def test_terms_change_between_discovery_and_election_blocks_post(catalog,owner_db):
    s=catalog
    def change():
        with owner_db.cursor() as q:q.execute("UPDATE usage_plans SET trial_days=13 WHERE plan_key='growth'")
    s.transport.during_read=change
    try:
        with pytest.raises(P.CatalogBlocked,match='terms changed'):sync(s)
        assert not s.transport.posts
    finally:
        with owner_db.cursor() as q:q.execute("UPDATE usage_plans SET trial_days=14 WHERE plan_key='growth'")


def test_effective_acl_force_rls_and_real_runtime_denial(catalog,owner_db):
    with owner_db.cursor() as q:
        q.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_catalog_operations'::regclass");assert q.fetchone()==(True,True)
        for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting','ceopro_consent_service','ceopro_billing_observer','ceopro_trial_issuer','ceopro_trial_attestor','ceopro_trial_confirmer','ceopro_journey_router'):
            q.execute("SELECT has_table_privilege(%s,'billing_catalog_operations','SELECT'),has_table_privilege(%s,'billing_catalog_operations','INSERT'),has_function_privilege(%s,'billing_catalog_operation_guard()','EXECUTE')",(role,role,role));assert q.fetchone()==(False,False,False)
    config=psycopg2.extensions.parse_dsn(catalog.dsn);config.update(user='ceopro_app',password=os.environ['APP_DB_PASSWORD'])
    with closing(psycopg2.connect(**config)) as conn:
        for statement in ('SELECT * FROM billing_catalog_operations','INSERT INTO billing_catalog_operations DEFAULT VALUES'):
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                with conn.cursor() as q:q.execute(statement)
            conn.rollback()
