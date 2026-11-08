"""Multi-gateway lifecycle proof: python -m scripts.verify_multi_gateway_billing --isolated-local.

New labelled PG17 container only, tmpfs, loopback; no application DB/providers.
Full production restricted installation is a separate release gate.
"""
import argparse
import ast
from contextlib import closing
import hashlib
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
import xml.etree.ElementTree as ET

import psycopg2
from psycopg2 import sql
from scripts.billing_verification import is_test_database_name
from scripts.verify_recurring_consent import local_docker_endpoint

ROOT=Path(__file__).resolve().parents[2]
NEW='20261209000000_neutral_subscription_lifecycle.sql'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-local',action='store_true',required=True)
    parser.add_argument('--select',action='append',help='Exact test node from the bounded consent/B4 selection')
    args=parser.parse_args()
    safe={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA'}}
    os.environ.clear();os.environ.update(safe)
    run=uuid.uuid4().hex[:12];name='keel-gateway-proof-'+run
    target=ROOT/'.dev/evidence/multi-gateway-billing'/run;target.mkdir(parents=True)
    password,runtime=secrets.token_hex(24),secrets.token_hex(24)
    env=dict(safe,POSTGRES_PASSWORD=password);started=False
    report=dict(status='RUNNING',scope='new local PG17, loopback, tmpfs, no volumes/providers')
    def docker(*args):
        value=subprocess.run(['docker',*args],env=env,capture_output=True,text=True)
        if value.returncode:raise RuntimeError('Isolated Docker failed: '+args[0])
        return value.stdout.strip()
    def authority(conn):
        roles=['ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting','ceopro_billing_observer','ceopro_trial_attestor','ceopro_trial_confirmer']
        with conn.cursor() as q:
            q.execute("SELECT r,p.oid,has_function_privilege(r,p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN unnest(%s::text[]) r WHERE n.nspname='public' ORDER BY 1,2",(roles,))
            return {(r,oid):value for r,oid,value in q.fetchall()}
    try:
        assert local_docker_endpoint(json.loads(docker('context','inspect'))[0]['Endpoints']['docker']['Host'])
        docker('run','-d','--pull=never','--name',name,'--label','keel.purpose=journey-isolated',
            '--tmpfs','/var/lib/postgresql/data:rw,size=768m','-p','127.0.0.1::5432','-e','POSTGRES_PASSWORD','pgvector/pgvector:pg17');started=True
        detail=json.loads(docker('inspect',name))[0]
        assert detail['Config']['Labels']['keel.purpose']=='journey-isolated'
        assert all(m['Type']=='tmpfs' for m in detail['Mounts'])
        assert detail['HostConfig']['PortBindings']['5432/tcp'][0]['HostIp']=='127.0.0.1'
        port=int(docker('port',name,'5432/tcp').removeprefix('127.0.0.1:'))
        fresh='keel_billing_test_journeyfresh'+run;upgrade='keel_billing_test_journeyupgrade'+run
        def connect(database='postgres'):
            assert database=='postgres' or is_test_database_name(database)
            return psycopg2.connect(host='127.0.0.1',port=port,dbname=database,user='postgres',password=password,connect_timeout=3,sslmode='disable',gssencmode='disable')
        for _ in range(30):
            try:
                with closing(connect()):break
            except psycopg2.OperationalError:time.sleep(1)
        else:raise RuntimeError('New disposable PostgreSQL unavailable')
        with closing(connect()) as conn:
            conn.autocommit=True
            with conn.cursor() as q:
                q.execute('SHOW server_version_num');assert 170000<=int(q.fetchone()[0])<180000
                q.execute('SELECT datname FROM pg_database WHERE NOT datistemplate');assert q.fetchall()==[('postgres',)]
                for database in (fresh,upgrade):q.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        os.environ.update(APP_DB_PASSWORD=runtime,BILLING_SETUP_DB_PASSWORD=runtime,
            BILLING_WEBHOOK_DB_PASSWORD=runtime,CREDIT_ACCOUNTING_DB_PASSWORD=runtime)
        from scripts import apply_migrations as M
        logging.getLogger('CEOPRO_MIGRATION_RUNNER').setLevel(logging.WARNING)
        source=M.MIGRATIONS_DIR
        with closing(connect(fresh)) as conn:
            report['fresh']=len(M.run(conn));assert report['fresh']==175 and M.run(conn)==[]
        with tempfile.TemporaryDirectory(dir=target) as tmp:
            for path in source.glob('*.sql'):
                if path.name!=NEW:shutil.copyfile(path,Path(tmp)/path.name)
            assert len(list(Path(tmp).glob('*.sql')))==174
            M.MIGRATIONS_DIR=Path(tmp)
            try:
                with closing(connect(upgrade)) as conn:assert len(M.run(conn))==174
            finally:M.MIGRATIONS_DIR=source
        with closing(connect(upgrade)) as conn:
            conn.autocommit=True
            before=authority(conn)
            with conn.cursor() as q:
                tid,uid=str(uuid.uuid4()),str(uuid.uuid4())
                q.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic historical business','US','USD')",(tid,))
                q.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'synthetic')",(uid,uid+'@example.test'))
                q.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",(tid,uid))
                q.execute("INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(%s,'growth',now()-interval '30 days',now()-interval '16 days',%s)",(tid,uid))
                q.execute('SELECT to_jsonb(t)::text FROM billing_trials t WHERE tenant_id=%s',(tid,));history=q.fetchone()
            conn.autocommit=False
            try:
                with conn.cursor() as q:
                    q.execute('ALTER ROLE ceopro_trial_confirmer LOGIN')
                    q.execute((source/NEW).read_text(encoding='utf-8'))
            except psycopg2.errors.InsufficientPrivilege:conn.rollback()
            else:raise AssertionError('Unsafe installer role model accepted')
            report['unsafe_role_model_rejected']=True
            try:
                with conn.cursor() as q:q.execute((source/NEW).read_text(encoding='utf-8')+'; SELECT 1/0;')
            except psycopg2.errors.DivisionByZero:conn.rollback()
            else:raise AssertionError('Expected rollback failure')
            with conn.cursor() as q:
                q.execute("SELECT to_regprocedure('billing_lifecycle_apply(uuid)')");assert q.fetchone()==(None,)
            conn.rollback();report['rollback']='PASS'
            assert M.run(conn)==[NEW] and M.run(conn)==[]
            after=authority(conn);assert all(after[k]==v for k,v in before.items())
            with conn.cursor() as q:
                q.execute("SELECT 'billing_journey_is_protected(text,text,text)'::regprocedure::oid,'billing_observation_setup_source(uuid,text)'::regprocedure::oid"); classifier,setup_source=q.fetchone()
            with conn.cursor() as q:
                q.execute("SELECT p.oid,p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'")
                names=dict(q.fetchall())
            allowed={'ceopro_trial_attestor':{'billing_lifecycle_context','billing_lifecycle_attest'},
                     'ceopro_trial_confirmer':{'billing_lifecycle_context','billing_lifecycle_apply'}}
            assert all(not v or names[k[1]] in allowed.get(k[0],set()) for k,v in after.items() if k not in before)

            conn.commit();conn.autocommit=True
            with conn.cursor() as q:
                q.execute('SELECT to_jsonb(t)::text FROM billing_trials t WHERE tenant_id=%s',(tid,));assert q.fetchone()==history
                q.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='ceopro_consent_service'");assert q.fetchone()==(False,)
                q.execute("SELECT count(*) FROM pg_auth_members WHERE roleid IN ('ceopro_consent_service'::regrole,'ceopro_consent_owner'::regrole)");assert q.fetchone()==(0,)
                q.execute("SELECT has_function_privilege('public','billing_consent_consumption_fence()','EXECUTE')");assert q.fetchone()==(False,)
                for role in ('ceopro_billing_observer','ceopro_trial_attestor','ceopro_trial_confirmer','ceopro_consent_service'):
                    q.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD %s').format(sql.Identifier(role)),(runtime,))
            report.update(upgrade='174 -> 175',existing_runtime_execute_unchanged=True,new_runtime_authority="no ordinary runtime EXECUTE/writes; tenant-scoped app settlement SELECT only",dormant_roles_no_memberships=True,historical_trial_unchanged=True)
        def dsn(role):return f'postgresql://{role}:{password if role=="postgres" else runtime}@127.0.0.1:{port}/{upgrade}'
        test_env=dict(safe,PYTHONPATH=str(ROOT/'backend'),PYTHONDONTWRITEBYTECODE='1',JWT_SECRET='synthetic-journey-local-only-secret-at-least-32-bytes',
            BILLING_DATABASE_TESTS='1',BILLING_TEST_DATABASE_URL=dsn('postgres'),SCRAPER_DATABASE_URL=dsn('ceopro_app'),DATABASE_URL=dsn('ceopro_app'),
            APP_DB_PASSWORD=runtime,BILLING_SETUP_DB_PASSWORD=runtime,BILLING_WEBHOOK_DB_PASSWORD=runtime,CREDIT_ACCOUNTING_DB_PASSWORD=runtime,
            OBSERVATION_TEST_PASSWORD=runtime,PUBLIC_FRONTEND_ORIGIN='http://127.0.0.1:19473',REQUIRE_EMAIL_VERIFICATION='false',
            A1_TEST_PG_PORT=str(port),A1_TEST_REDIS_PORT=str(port))
        # Reuse the accepted socket/libpq guard, but allow only this owned PG port.
        tree=ast.parse((ROOT/'backend/scripts/verify_recurring_consent.py').read_text())
        guard=next(n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='guard' for t in n.targets))
        selected=['tests/billing/test_multi_gateway_lifecycle_db.py','tests/billing/test_multi_gateway_adapters.py',
            'tests/billing/test_trial_confirmation_db.py::test_atomic_confirmation_and_exact_repeat_preserve_cutoff_and_credits',
            'tests/billing/test_consent_withdrawal_db.py',
            'tests/billing/test_subscription_journey_db.py',
            'tests/billing/test_reconciliation_roles.py::test_signed_activation_renewal_failure_recovery_and_cancel',
            'tests/billing/test_reconciliation_roles.py::test_custom_paid_activation_and_frozen_limits_use_webhook_role',
            'tests/billing/test_trial_plan_transitions.py::test_paid_downgrade_preserves_paid_period_and_failed_renewal_denies']
        if args.select:
            assert all(node.split('::',1)[0] in {s.split('::',1)[0] for s in selected} for node in args.select), 'Test selection outside focused boundary'
            selected=args.select
        else:
            selected+=['-k','not active_signup_workspace_and_trial_remain_compatible']
        command=[sys.executable,'-B','-c',guard,*selected,'-q','-p','no:cacheprovider','--junitxml='+str(target/'junit.xml')]
        report['selected']=selected
        with (target/'pytest.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(command,cwd=ROOT/'backend',env=test_env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        suite=ET.parse(target/'junit.xml').getroot();counts={key:sum(int(s.get(key,'0')) for s in suite.iter('testsuite')) for key in ('tests','failures','errors','skipped')}
        report['tests']=counts
        assert result.returncode==0 and not any(counts[k] for k in ('failures','errors','skipped')),'Focused test failure; inspect private pytest.log'
        report['status']='PASS'
    except BaseException as error:
        report.update(status='FAIL',error_type=type(error).__name__);raise
    finally:
        if started:docker('stop',name)
        report.update(container=name,stopped=started,production_restricted_installer_verified=False)
        (target/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2));print('Evidence:',target)


if __name__=='__main__':main()
