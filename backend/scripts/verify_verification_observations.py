"""Explicit local-only B3 proof (adapted from the guarded Customer verifier). Uses installed PG17/Redis images, no volumes.

Run from backend: python -m scripts.verify_verification_observations --isolated-local
Never loads .env, uses an existing DSN, or touches existing containers/databases.
The uniquely labelled test container is stopped on exit; evidence is retained.
"""
import argparse
import hashlib
from contextlib import closing, ExitStack
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg2
from scripts.verification_migrations import phase_migrations
from psycopg2 import sql
from scripts.billing_verification import is_test_database_name

ROOT=Path(__file__).resolve().parents[2]
NEW=('20261203000000_trusted_trial_observations.sql',)


def migration_verification_scope():
    """Describe unexecuted coverage and fixture authority without inventing results.

    Completed migration checks are added by main only after their assertions pass.
    This report does not certify production least-privilege installation.
    """
    return {
        'full_restricted_runner': {
            'execution': 'NOT_EXECUTED',
            'result': None,
            'merge_gate': 'UNVERIFIED',
            'note': ('Possible Standard Plan Catalog / FORCE RLS incompatibility is '
                     'source-inferred, not a reproduced failure in this verification. '
                     'Full restricted runner execution, including post-install, remains required.'),
        },
        'installer_fixture_authority': {
            'authentication': 'password',
            'superuser': False,
            'bypassrls': False,
            'createrole': True,
            'ownership': 'public schema and existing public tables',
            'temporary_membership': 'ceopro_trial_issuer: SET TRUE; ceopro_observation_owner: ADMIN TRUE, SET TRUE; INHERIT FALSE (isolated installer fixture only)',
            'explicit_execute': ['billing_standard_catalog_install(jsonb,text,boolean)',
                                 'billing_catalog_reconcile()', 'keel_active_principal(uuid,uuid): WITH GRANT OPTION (installation-only fixture)'],
            'production_least_privilege_verified': False,
        },
    }


def local_docker_endpoint(endpoint):
    return endpoint in {'npipe:////./pipe/dockerDesktopLinuxEngine', 'npipe:////./pipe/docker_engine'} or endpoint.startswith('unix:///')


def main():
    phase_stack = ExitStack()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-local',action='store_true',required=True)
    parser.parse_args()
    # No inherited database, Stripe, cloud or application secrets.
    safe={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA'}}
    os.environ.clear();os.environ.update(safe)
    run_id=uuid.uuid4().hex[:12]
    name='keel-observation-'+run_id
    target=ROOT/'.dev/evidence/phase1-3e-b3'/run_id;target.mkdir(parents=True)
    password=secrets.token_hex(24)
    runtime_password=secrets.token_hex(24)
    env=dict(safe,POSTGRES_PASSWORD=password,REDIS_TEST_PASSWORD=runtime_password)
    def docker(*args):
        result=subprocess.run(['docker',*args],env=env,capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Isolated Docker operation failed: '+args[0])
        return result.stdout.strip()
    endpoint=json.loads(docker('context','inspect'))[0]['Endpoints']['docker']['Host']
    if not local_docker_endpoint(endpoint):
        raise RuntimeError('Only a local Docker socket is permitted for this proof')
    # --pull=never refuses network downloads. No external interfaces or volumes.
    docker('run','-d','--pull=never','--name',name,'--label','keel.purpose=observation-isolated-test',
           '--tmpfs','/var/lib/postgresql/data:rw,size=768m','-p','127.0.0.1::5432',
           '-e','POSTGRES_PASSWORD','pgvector/pgvector:pg17')
    report={'container':name,'image':'pgvector/pgvector:pg17','scope':'loopback-only, tmpfs, no volumes','status':'running',
            **migration_verification_scope()}
    report['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
        ROOT/'backend/src/infrastructure/database/migrations'/NEW[0],
        ROOT/'backend/src/ai/billing/verification_observations.py',ROOT/'backend/src/ai/billing/payment_contracts.py',
        ROOT/'backend/tests/billing/test_verification_observations.py',ROOT/'backend/tests/billing/test_verification_observations_db.py',
        Path(__file__).resolve()]}
    redis_started=False
    redis_name=name+'-redis'
    try:
        # Isolated dependency for existing Credit/search-safety regression tests.
        # No shared Redis, host storage, persistence or image downloads.
        docker('image','inspect','redis:7-alpine')
        docker('run','-d','--pull=never','--name',redis_name,'--label','keel.purpose=observation-isolated-test',
               '--tmpfs','/data:rw,size=32m','-p','127.0.0.1::6379','-e','REDIS_TEST_PASSWORD',
               '--entrypoint','sh','redis:7-alpine','-c',
               'exec redis-server --save "" --appendonly no --maxmemory 32mb --maxmemory-policy noeviction --requirepass "$REDIS_TEST_PASSWORD"')
        redis_started=True
        redis_port=int(docker('port',redis_name,'6379/tcp').removeprefix('127.0.0.1:'))
        import redis
        cache=redis.Redis(host='127.0.0.1',port=redis_port,password=runtime_password,decode_responses=True)
        assert cache.ping() and cache.dbsize()==0, 'Fresh isolated Redis required'
        cache.close()
        report['redis']={'container':redis_name,'host':'127.0.0.1','port':redis_port,'fresh_empty':True,'persistent':False}
        port=int(docker('port',name,'5432/tcp').removeprefix('127.0.0.1:'))
        report['port']=port
        owned=json.loads(docker('inspect',name))[0]
        assert owned['Config']['Labels']['keel.purpose']=='observation-isolated-test'
        assert all(m['Type']=='tmpfs' for m in owned['Mounts'])
        assert owned['HostConfig']['PortBindings']['5432/tcp'][0]['HostIp']=='127.0.0.1'
        def connect(database='postgres',user='postgres',secret=password):
            assert database=='postgres' or is_test_database_name(database)
            return psycopg2.connect(host='127.0.0.1',port=port,dbname=database,user=user,password=secret,
                                    connect_timeout=3,sslmode='disable',gssencmode='disable')
        for _ in range(30):
            try:
                with closing(connect()) as conn:break
            except psycopg2.OperationalError:time.sleep(1)
        else:raise RuntimeError('Isolated PostgreSQL did not become ready')
        fresh='keel_billing_test_c2bfresh'+run_id
        upgrade='keel_billing_test_c2bupgrade'+run_id
        failure='keel_billing_test_c2bfailure'+run_id
        report['databases']=[fresh,upgrade,failure]
        with closing(connect()) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:
                cur.execute('SHOW server_version_num');assert 170000<=int(cur.fetchone()[0])<180000
                cur.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")
                assert cur.fetchall()==[('postgres',)], 'New isolated cluster required'
                for database in (fresh,upgrade):
                    assert is_test_database_name(database)
                    cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        # Prove newly created identity and empty state BEFORE migration invocation.
        for database in (fresh,upgrade):
            with closing(connect(database)) as conn,conn.cursor() as cur:
                cur.execute("SELECT current_database(),to_regclass('public.companies'),to_regclass('public.schema_migrations')")
                assert cur.fetchone()==(database,None,None)
        from scripts import apply_migrations as migrations
        scope = phase_stack.enter_context(phase_migrations(migrations, NEW, target))
        report['migration_manifest'] = scope.report()
        logging.getLogger('CEOPRO_MIGRATION_RUNNER').setLevel(logging.WARNING)
        os.environ.update(APP_DB_PASSWORD=runtime_password,BILLING_SETUP_DB_PASSWORD=runtime_password)
        with closing(connect(fresh)) as conn:
            assert len(migrations.run(conn))==scope.count
            assert migrations.run(conn)==[]
            with conn.cursor() as cur:
                for table in ('billing_gateway_bindings','billing_customer_references','billing_price_references','billing_trial_checkouts','billing_customer_operations','billing_observation_operations','billing_observation_receipts','billing_verification_observations'):
                    cur.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)))
                    assert cur.fetchone()==(0,), 'No automatic bindings, mappings or reservations'
        report['fresh_migrations']=scope.count
        report['fresh_installation']={'execution':'EXECUTED','result':'PASS',
                                      'authority':'postgres superuser; full runner and replay'}
        source=migrations.MIGRATIONS_DIR
        with tempfile.TemporaryDirectory(dir=target) as temporary:
            for path in source.glob('*.sql'):
                if path.name not in NEW:shutil.copyfile(path,Path(temporary)/path.name)
            assert len(list(Path(temporary).glob('*.sql')))==scope.baseline_count
            migrations.MIGRATIONS_DIR=Path(temporary)
            with closing(connect(upgrade)) as conn:assert len(migrations.run(conn))==scope.baseline_count
        migrations.MIGRATIONS_DIR=source
        with closing(connect(upgrade)) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:
                for number in range(3):
                    tid,uid=str(uuid.uuid4()),str(uuid.uuid4())
                    cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic historical fixture','US','USD')",(tid,))
                    cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')",(uid,uid+'@example.test'))
                    cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",(tid,uid))
                    if number==0:
                        cur.execute("INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,'cus_history')",(tid,))
                        cur.execute("INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,plan_key,period_code,status) VALUES(%s,'sub_history','cus_history','growth','monthly','active')",(tid,))
                        cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,'growth','active','stripe')",(tid,))
                    elif number==1:
                        cur.execute("INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(%s,'growth',now()-interval '30 days',now()-interval '16 days',%s)",(tid,uid))
                        cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,'growth','expired','trial')",(tid,))
                    else:
                        cur.execute("INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code,state,stripe_session_id,provider_params) VALUES(gen_random_uuid(),%s,'legacy','growth','monthly','open','cs_history',jsonb_build_object('synthetic',true))",(tid,))
        with closing(connect()) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(failure),sql.Identifier(upgrade)))
        def fingerprints(conn):
            result={}
            with conn.cursor() as cur:
                for table in ('billing_customers','billing_subscriptions','billing_trials','billing_checkout_attempts','tenant_plan_assignments','tenant_credit_balances','usage_ledger'):
                    cur.execute(sql.SQL("SELECT coalesce(jsonb_agg(to_jsonb(t)-%s::text[] ORDER BY to_jsonb(t)::text),'[]')::text FROM {} t").format(sql.Identifier(table)),
                                (['gateway_binding_id','provider_idempotency_key','provider_session_id','first_submitted_at','replay_window_seconds'],))
                    result[table]=cur.fetchone()[0]
                cur.execute("SELECT pg_get_functiondef('billing_setup_trial(text,boolean)'::regprocedure)")
                result['legacy_trial_function']=cur.fetchone()[0]
            return result
        # Actual restricted installer login; installation authority is fixture-only.
        with closing(connect(upgrade)) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:
                cur.execute('CREATE ROLE c2b_installer LOGIN CREATEROLE NOINHERIT PASSWORD %s',(runtime_password,))
                cur.execute('ALTER SCHEMA public OWNER TO c2b_installer')
                cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                for (table,) in cur.fetchall():cur.execute(sql.SQL('ALTER TABLE public.{} OWNER TO c2b_installer').format(sql.Identifier(table)))
                cur.execute('GRANT ceopro_trial_issuer TO c2b_installer WITH SET TRUE, INHERIT FALSE')
                cur.execute('GRANT ceopro_observation_owner TO c2b_installer WITH ADMIN TRUE, SET TRUE, INHERIT FALSE')
                # Explicit installation-only authority, never granted to runtime roles.
                cur.execute('GRANT EXECUTE ON FUNCTION billing_standard_catalog_install(jsonb,text,boolean),billing_catalog_reconcile() TO c2b_installer')
                cur.execute('GRANT EXECUTE ON FUNCTION keel_active_principal(uuid,uuid) TO c2b_installer WITH GRANT OPTION')
            before=fingerprints(conn)
        with closing(connect(upgrade,'c2b_installer',runtime_password)) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT session_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
                assert cur.fetchone()==('c2b_installer',False,False)
            conn.rollback()
            # Test exactly the new files with the existing SQL-file executor and
            # ledger transaction contract. The legacy post-install catalog is a
            # separate authority boundary, not weakened for this proof.
            migrations._allow_owner_role_management(conn)
            for filename in NEW:
                try:
                    migrations._apply_sql_file(conn,source/filename)
                    with conn.cursor() as cur:cur.execute('INSERT INTO schema_migrations(filename) VALUES(%s)',(filename,))
                    conn.commit()
                except BaseException:
                    conn.rollback();raise
            # Preserve the integrity assertion through the SAME isolated fixture
            # observer that captured `before`. Separately prove installer RLS.
            with conn.cursor() as cur:
                cur.execute('SELECT count(*) FROM billing_customers')
                assert cur.fetchone()==(0,), 'Installer must remain FORCE-RLS filtered'
            with closing(connect(upgrade)) as observer:
                assert fingerprints(observer)==before, 'Historical fixture data changed'
            with conn.cursor() as cur:
                cur.execute("SELECT has_schema_privilege('ceopro_trial_issuer','public','CREATE')")
                assert cur.fetchone()==(False,)
        with closing(connect(upgrade)) as conn:
            with conn.cursor() as cur:cur.execute('REVOKE ceopro_observation_owner FROM c2b_installer')
            conn.commit()
            assert migrations.run(conn)==[]
            assert fingerprints(conn)==before
        report.update(upgrade_migrations=scope.count,legacy_fingerprints_unchanged=True,restricted_installer_new_files=True,
                      populated_upgrade={'execution':'EXECUTED','result':'PASS',
                                         'authority':'postgres named-phase baseline/observer/replay; fixture installer for B3 only'},
                      restricted_new_migrations={'execution':'EXECUTED','result':'PASS',
                                                 'files':list(NEW),
                                                 'scope':'SQL-file executor and ledger transactions; not full runner'})
        with closing(connect(failure)) as conn:
            try:
                with conn.cursor() as cur:cur.execute((source/NEW[0]).read_text()+'; SELECT 1/0;')
            except psycopg2.errors.DivisionByZero:conn.rollback()
            else:raise AssertionError('Injected migration failure did not fail')
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.billing_observation_operations'),(SELECT count(*) FROM schema_migrations)")
                assert cur.fetchone()==(None,scope.baseline_count)
        report['failed_migration_rollback']=True
        with closing(connect(upgrade)) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:
                cur.execute('REVOKE ceopro_trial_issuer FROM c2b_installer')
                for observer in ('ceopro_billing_observer','ceopro_observation_owner'):
                    cur.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit FROM pg_roles WHERE rolname=%s",(observer,))
                    assert cur.fetchone()==(False,False,False,False,False,False)
                    cur.execute("SELECT count(*) FROM pg_auth_members WHERE roleid=%s::regrole OR member=%s::regrole",(observer,observer))
                    assert cur.fetchone()==(0,)
                cur.execute('ALTER ROLE ceopro_billing_observer LOGIN PASSWORD %s',(runtime_password,))
                for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting'):
                    cur.execute(sql.SQL('ALTER ROLE {} PASSWORD %s').format(sql.Identifier(role)),(runtime_password,))
        with closing(connect(upgrade)) as conn,conn.cursor() as cur:
            cur.execute("SELECT p.proname,p.proacl::text,has_function_privilege('ceopro_app',p.oid,'EXECUTE'),has_function_privilege('ceopro_billing_webhook',p.oid,'EXECUTE') FROM pg_proc p WHERE p.proname=ANY(%s)",
                        (['billing_observation_begin','billing_observation_claim','billing_observation_record','billing_observation_notification'],))
            report['new_command_acls']=cur.fetchall()
            assert all(not app and not webhook for _,_,app,webhook in report['new_command_acls'])
        test_env=dict(safe,PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',BILLING_DATABASE_TESTS='1',AI_TEST_MODE='1',
                      JWT_SECRET='isolated-billing-test-not-for-deployment',APP_DB_PASSWORD=runtime_password,
                      FRONTEND_BASE_URL='http://localhost:5173',BILLING_SETUP_DB_PASSWORD=runtime_password,
                      BILLING_WEBHOOK_DB_PASSWORD=runtime_password,CREDIT_ACCOUNTING_DB_PASSWORD=runtime_password,OBSERVATION_TEST_PASSWORD=runtime_password)
        def dsn(user):return f'postgresql://{user}:{password if user=="postgres" else runtime_password}@127.0.0.1:{port}/{upgrade}'
        test_env.update(BILLING_TEST_DATABASE_URL=dsn('postgres'),SCRAPER_DATABASE_URL=dsn('ceopro_app'),DATABASE_URL=dsn('ceopro_app'),
                        REDIS_URL=f'redis://:{runtime_password}@127.0.0.1:{redis_port}/0')
        selected=['tests/billing/test_verification_observations.py','tests/billing/test_verification_observations_db.py',
                  'tests/billing/test_provider_verification_contracts.py','tests/billing/test_stripe_verification.py',
                  'tests/billing/test_customer_contracts.py','tests/billing/test_customer_operations_db.py',
                  'tests/billing/test_payment_bindings_db.py','tests/billing/test_payment_contracts.py',
                  'tests/billing/test_payment_gateway.py','tests/billing/test_payment_outbound.py',
                  'tests/billing/test_payment_reconciliation.py','tests/billing/test_payment_webhook_decoder.py',
                  'tests/billing/test_trial_plan_transitions.py','tests/billing/test_contract.py',
                  'tests/billing/test_checkout_reservations.py','tests/billing/test_custom_checkout_contract.py',
                  'tests/billing/test_custom_webhook_contract.py','tests/billing/test_provider_accounting_db.py',
                  'tests/billing/test_reconciliation_roles.py','tests/billing/test_payment_persistence_reporting.py']
        # Guard all Python sockets and libpq connections independently of fixtures.
        guard = """import socket,psycopg2,os,sys,threading
from urllib.parse import urlsplit
allowed={int(os.environ['B3_TEST_PG_PORT']),int(os.environ['B3_TEST_REDIS_PORT'])}
original_connect=socket.socket.connect
pair_context=threading.local()
original_pair=socket.socketpair
def own_pair(*args,**kwargs):
    pair_context.active=True
    try: return original_pair(*args,**kwargs)
    finally: pair_context.active=False
socket.socketpair=own_pair
def guarded_socket(self,address):
    if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','localhost','::1') or (address[1] not in allowed and not getattr(pair_context,'active',False)): raise AssertionError('External socket forbidden')
    return original_connect(self,address)
socket.socket.connect=guarded_socket
original_lookup=socket.getaddrinfo
def lookup(host,*args,**kwargs):
    if host not in ('127.0.0.1','localhost','::1'): raise AssertionError('External DNS forbidden')
    return original_lookup(host,*args,**kwargs)
socket.getaddrinfo=lookup
original_pg=psycopg2.connect
def pg(dsn=None,*args,**kwargs):
    values=psycopg2.extensions.parse_dsn(dsn) if dsn else {}
    values.update(kwargs)
    if values.get('host') not in ('127.0.0.1','localhost','::1') or int(values.get('port',0))!=int(os.environ['B3_TEST_PG_PORT']) or not values.get('dbname','').startswith('keel_billing_test_'): raise AssertionError('Nonisolated libpq connection forbidden')
    return original_pg(dsn,*args,**kwargs)
psycopg2.connect=pg
import pytest
sys.exit(pytest.main(sys.argv[1:]))
"""
        test_env.update(B3_TEST_PG_PORT=str(port),B3_TEST_REDIS_PORT=str(redis_port))
        command=[sys.executable,'-B','-c',guard,*selected,'-q','-ra','-p','no:cacheprovider','--junitxml='+str(target/'junit.xml')]
        with (target/'pytest.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(command,cwd=ROOT/'backend',env=test_env,capture_output=True,text=True)
            log.write((result.stdout+result.stderr).replace(password,'[redacted]').replace(runtime_password,'[redacted]'))
        import xml.etree.ElementTree as ET
        suites=ET.parse(target/'junit.xml').getroot().findall('testsuite')
        report['tests']={key:sum(int(s.get(key,'0')) for s in suites) for key in ('tests','failures','errors','skipped')}
        assert result.returncode==0 and report['tests']['skipped']==0, 'Focused tests failed; inspect sanitized local pytest.log'
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in report['source_hashes'].items()), 'Source changed during verification'
        report['status']='executed_checks_passed'
    except BaseException:
        report['status']='failed'
        raise
    finally:
        try:
            phase_stack.close()
        finally:
            if redis_started:
                docker('stop',redis_name)
                report['redis_stopped']=True
            docker('stop',name)
            report['container_stopped']=True
            (target/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2));print('Evidence:',target)
    return 0


if __name__=='__main__':raise SystemExit(main())
