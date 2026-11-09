"""A2 local disposable PG17 proof. No inherited DSN, provider call or shared volume.
Run from backend: python -B -m scripts.verify_evidence_progression --isolated-local
Fresh chain, populated 171->172 upgrade/replay, ACL equality and focused native tests.
Installation uses a disposable superuser; production restricted installation is unverified.
"""
import argparse
from contextlib import closing, ExitStack
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
from scripts.verification_migrations import phase_migrations
from psycopg2 import sql
from scripts.verify_recurring_consent import local_docker_endpoint

ROOT = Path(__file__).resolve().parents[2]
NEW = '20261206000000_trial_evidence_progression.sql'
GUARD = "import socket,psycopg2,os,sys,threading\nfrom urllib.parse import urlsplit\nallowed={int(os.environ['A1_TEST_PG_PORT']),int(os.environ['A1_TEST_REDIS_PORT'])}\noriginal_connect=socket.socket.connect\npair_context=threading.local()\noriginal_pair=socket.socketpair\ndef own_pair(*args,**kwargs):\n    pair_context.active=True\n    try: return original_pair(*args,**kwargs)\n    finally: pair_context.active=False\nsocket.socketpair=own_pair\ndef guarded_socket(self,address):\n    if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','localhost','::1') or (address[1] not in allowed and not getattr(pair_context,'active',False)): raise AssertionError('External socket forbidden')\n    return original_connect(self,address)\nsocket.socket.connect=guarded_socket\noriginal_lookup=socket.getaddrinfo\ndef lookup(host,*args,**kwargs):\n    if host not in ('127.0.0.1','localhost','::1'): raise AssertionError('External DNS forbidden')\n    return original_lookup(host,*args,**kwargs)\nsocket.getaddrinfo=lookup\noriginal_pg=psycopg2.connect\ndef pg(dsn=None,*args,**kwargs):\n    values=psycopg2.extensions.parse_dsn(dsn) if dsn else {}\n    values.update(kwargs)\n    if values.get('host') not in ('127.0.0.1','localhost','::1') or int(values.get('port',0))!=int(os.environ['A1_TEST_PG_PORT']) or not values.get('dbname','').startswith('keel_billing_test_'): raise AssertionError('Nonisolated libpq connection forbidden')\n    return original_pg(dsn,*args,**kwargs)\npsycopg2.connect=pg\nimport pytest\nsys.exit(pytest.main(sys.argv[1:]))\n"


def main():
    phase_stack = ExitStack()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-local', action='store_true', required=True)
    parser.parse_args()
    safe = {k:v for k,v in os.environ.items() if k.upper() in
            {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA'}}
    os.environ.clear(); os.environ.update(safe)
    run_id = uuid.uuid4().hex[:12]
    name = 'keel-a2-'+run_id
    target = ROOT/'.dev/evidence/phase1-3d-a2'/run_id
    target.mkdir(parents=True)
    password, runtime = secrets.token_hex(24), secrets.token_hex(24)
    env = dict(safe, POSTGRES_PASSWORD=password, REDIS_TEST_PASSWORD=runtime)
    owned = []
    report = dict(status='running', installation_authority='disposable superuser', production_restricted_installer='UNVERIFIED')
    paths = [ROOT/'backend/src/infrastructure/database/migrations'/NEW,
             ROOT/'backend/src/ai/billing/stripe_verification.py',
             ROOT/'backend/tests/billing/test_evidence_progression_db.py', Path(__file__).resolve()]
    report['source_hashes'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    def docker(*args):
        result = subprocess.run(['docker',*args], env=env, capture_output=True, text=True)
        if result.returncode: raise RuntimeError('Isolated Docker operation failed: '+args[0])
        return result.stdout.strip()
    try:
        endpoint = json.loads(docker('context','inspect'))[0]['Endpoints']['docker']['Host']
        assert local_docker_endpoint(endpoint), 'Local Docker required'
        for suffix, image, container_port, storage, command in [
            ('', 'pgvector/pgvector:pg17', '5432', '/var/lib/postgresql/data:rw,size=768m', ['-e','POSTGRES_PASSWORD']),
            ('-redis', 'redis:7-alpine', '6379', '/data:rw,size=32m', ['-e','REDIS_TEST_PASSWORD','--entrypoint','sh'])]:
            args = ['run','-d','--pull=never','--name',name+suffix,'--label','keel.purpose=a2-isolated-test',
                    '--tmpfs',storage,'-p','127.0.0.1::'+container_port,*command,image]
            if suffix:
                args += ['-c','exec redis-server --save "" --appendonly no --requirepass "$REDIS_TEST_PASSWORD"']
            docker(*args); owned.append(name+suffix)
            detail = json.loads(docker('inspect',name+suffix))[0]
            assert detail['Config']['Labels']['keel.purpose']=='a2-isolated-test'
            assert all(m['Type']=='tmpfs' for m in detail['Mounts'])
            assert detail['HostConfig']['PortBindings'][container_port+'/tcp'][0]['HostIp']=='127.0.0.1'
        port = int(docker('port',name,'5432/tcp').removeprefix('127.0.0.1:'))
        redis_port = int(docker('port',name+'-redis','6379/tcp').removeprefix('127.0.0.1:'))
        report.update(containers=list(owned), pg_port=port, redis_port=redis_port)
        def connect(database='postgres'):
            assert database=='postgres' or database.startswith('keel_billing_test_a2')
            return psycopg2.connect(host='127.0.0.1',port=port,dbname=database,user='postgres',password=password,
                                    connect_timeout=3,sslmode='disable',gssencmode='disable')
        for _ in range(30):
            try:
                with closing(connect()) as conn: break
            except psycopg2.OperationalError: time.sleep(1)
        else: raise RuntimeError('Isolated PostgreSQL unavailable')
        import redis
        cache = redis.Redis(host='127.0.0.1',port=redis_port,password=runtime)
        assert cache.ping() and cache.dbsize()==0
        cache.close()
        fresh, upgrade = ('keel_billing_test_a2'+kind+run_id for kind in ('fresh','upgrade'))
        with closing(connect()) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute('SHOW server_version_num'); assert 170000<=int(cur.fetchone()[0])<180000
                cur.execute('SELECT datname FROM pg_database WHERE NOT datistemplate'); assert cur.fetchall()==[('postgres',)]
                for database in (fresh,upgrade):
                    cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        from scripts import apply_migrations as migrations
        scope = phase_stack.enter_context(phase_migrations(migrations, NEW, target))
        report['migration_manifest'] = scope.report()
        logging.getLogger('CEOPRO_MIGRATION_RUNNER').setLevel(logging.WARNING)
        os.environ.update(APP_DB_PASSWORD=runtime,BILLING_SETUP_DB_PASSWORD=runtime)
        for database in (fresh,upgrade):
            with closing(connect(database)) as conn, conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.companies'),to_regclass('public.schema_migrations')")
                assert cur.fetchone()==(None,None)
        with closing(connect(fresh)) as conn:
            assert len(migrations.run(conn))==scope.count and migrations.run(conn)==[]
        report['fresh_migrations']=scope.count
        migration_dir = migrations.MIGRATIONS_DIR
        with tempfile.TemporaryDirectory(dir=target) as temporary:
            for path in migration_dir.glob('*.sql'):
                if path.name!=NEW: shutil.copyfile(path,Path(temporary)/path.name)
            assert len(list(Path(temporary).glob('*.sql')))==scope.baseline_count
            try:
                migrations.MIGRATIONS_DIR=Path(temporary)
                with closing(connect(upgrade)) as conn: assert len(migrations.run(conn))==scope.baseline_count
            finally: migrations.MIGRATIONS_DIR=migration_dir
        roles = ['ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting',
                 'ceopro_billing_observer','ceopro_trial_attestor','ceopro_trial_confirmer','ceopro_consent_service']
        def facts(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'schema_migrations' ORDER BY 1")
                tables=[r[0] for r in cur.fetchall()]
                hashes=[]
                for table in tables:
                    cur.execute(sql.SQL("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text FROM {} t").format(sql.Identifier(table)))
                    hashes.append((table,hashlib.sha256(cur.fetchone()[0].encode()).hexdigest()))
                cur.execute("SELECT r,p.oid,has_function_privilege(r,p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN unnest(%s::text[]) r WHERE n.nspname='public' AND p.proname<>'billing_confirmation_progresses' ORDER BY 1,2",(roles,))
                acls=cur.fetchall()
                cur.execute('SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=ANY(%s) ORDER BY 1',(roles,))
                return hashes,acls,cur.fetchall()
        with closing(connect(upgrade)) as conn:
            conn.autocommit=True
            with conn.cursor() as cur:
                for kind in ('paid','trial'):
                    tenant,user=str(uuid.uuid4()),str(uuid.uuid4())
                    cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic A2 history','US','USD')",(tenant,))
                    cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'synthetic')",(user,user+'@example.test'))
                    cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",(tenant,user))
                    if kind=='paid':
                        cur.execute("INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,'cus_a2_history')",(tenant,))
                        cur.execute("INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,plan_key,period_code,status) VALUES(%s,'sub_a2_history','cus_a2_history','growth','monthly','active')",(tenant,))
                    else:
                        cur.execute("INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(%s,'growth',now()-interval '30 days',now()-interval '16 days',%s)",(tenant,user))
            before=facts(conn)
            # The new file is transactionally rollback-safe before real upgrade.
            conn.autocommit=False
            try:
                with conn.cursor() as cur: cur.execute((migration_dir/NEW).read_text()+'; SELECT 1/0;')
            except psycopg2.errors.DivisionByZero: conn.rollback()
            else: raise AssertionError('Injected failure did not fail')
            with conn.cursor() as cur:
                cur.execute("SELECT to_regprocedure('billing_confirmation_progresses(jsonb,jsonb)'),count(*) FROM schema_migrations")
                assert cur.fetchone()==(None,scope.baseline_count)
            conn.rollback()
            report['rollback']=True
            assert migrations.run(conn)==[NEW] and migrations.run(conn)==[]
            assert facts(conn)==before, 'Existing data or authority changed'
            report.update(upgrade=f'{scope.baseline_count}->{scope.count}',replay=True,data_and_existing_runtime_acls_unchanged=True)
            with conn.cursor() as cur:
                cur.execute("SELECT r,has_function_privilege(r,'billing_confirmation_progresses(jsonb,jsonb)','EXECUTE') FROM unnest(%s::text[]) r",(roles,))
                assert all(not granted for _,granted in cur.fetchall())
                for role in ('ceopro_billing_observer','ceopro_trial_attestor','ceopro_trial_confirmer','ceopro_consent_service'):
                    cur.execute('SELECT rolcanlogin,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s',(role,)); assert cur.fetchone()==(False,False,False)
                    cur.execute('SELECT count(*) FROM pg_auth_members WHERE roleid=%s::regrole OR member=%s::regrole',(role,role)); assert cur.fetchone()==(0,)
                    cur.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD %s').format(sql.Identifier(role)),(runtime,))
                for role in roles[:4]:
                    cur.execute(sql.SQL('ALTER ROLE {} PASSWORD %s').format(sql.Identifier(role)),(runtime,))
            conn.commit()
        def dsn(role): return f'postgresql://{role}:{password if role=="postgres" else runtime}@127.0.0.1:{port}/{upgrade}'
        test_env=dict(safe,PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',BILLING_DATABASE_TESTS='1',AI_TEST_MODE='1',
            JWT_SECRET='isolated-a2-not-for-deployment',APP_DB_PASSWORD=runtime,BILLING_SETUP_DB_PASSWORD=runtime,
            BILLING_WEBHOOK_DB_PASSWORD=runtime,CREDIT_ACCOUNTING_DB_PASSWORD=runtime,OBSERVATION_TEST_PASSWORD=runtime,
            FRONTEND_BASE_URL='http://localhost:5173',BILLING_TEST_DATABASE_URL=dsn('postgres'),DATABASE_URL=dsn('ceopro_app'),
            SCRAPER_DATABASE_URL=dsn('ceopro_app'),REDIS_URL=f'redis://:{runtime}@127.0.0.1:{redis_port}/0',
            A1_TEST_PG_PORT=str(port),A1_TEST_REDIS_PORT=str(redis_port))
        selected=['tests/billing/test_evidence_progression_db.py','tests/billing/test_verification_observations_db.py',
                  'tests/billing/test_trial_confirmation_db.py',
                  'tests/billing/test_recurring_consent_db.py::test_effective_acl_real_logins_and_no_set_role',
                  'tests/billing/test_recurring_consent_db.py::test_force_rls_and_owner_scope_with_no_public_execute']
        command=[sys.executable,'-B','-c',GUARD,*selected,'-q','-ra','-p','no:cacheprovider','--junitxml='+str(target/'junit.xml')]
        result=subprocess.run(command,cwd=ROOT/'backend',env=test_env,capture_output=True,text=True)
        (target/'pytest.log').write_text((result.stdout+result.stderr).replace(password,'[redacted]').replace(runtime,'[redacted]'),encoding='utf-8')
        suites=ET.parse(target/'junit.xml').getroot().findall('testsuite')
        report['tests']={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
        assert result.returncode==0 and report['tests']['skipped']==0, 'Focused native tests failed; inspect private pytest.log'
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in report['source_hashes'].items())
        report['status']='PASS'
    except BaseException:
        report['status']='FAIL'
        raise
    finally:
        try:
            phase_stack.close()
        finally:
            for container in reversed(owned): docker('stop',container)
            report['owned_containers_stopped']=True
            (target/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2)); print('Evidence:',target)
    return 0


if __name__=='__main__': raise SystemExit(main())
