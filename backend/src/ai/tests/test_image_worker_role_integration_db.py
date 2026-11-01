"""Exercise the image queue through its restricted runtime identity."""
import os
import subprocess
import sys
import time
import uuid

import psutil
import psycopg2
import pytest

DATABASE_URL = os.getenv('AI_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv('IMAGE_WORKER_DB_PASSWORD'),
                                reason='disposable DB and image worker credential required')


def test_image_worker_role_claim_and_heartbeat():
    from src.ai import db
    from src.ai.marketing import image_jobs

    tenant, campaign, job = (str(uuid.uuid4()) for _ in range(3))
    worker_id = 'role-test-' + uuid.uuid4().hex
    with psycopg2.connect(DATABASE_URL) as admin:
        with admin.cursor() as cur:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES (%s,'worker role test','JO','JOD')", (tenant,))
            cur.execute("INSERT INTO campaigns(tenant_id,campaign_id,campaign_brief) VALUES (%s,%s,'test')", (tenant, campaign))
            cur.execute("INSERT INTO image_generation_jobs(job_id,tenant_id,campaign_id,batch_id,image_format) VALUES (%s,%s,%s,%s,'SQUARE')", (job, tenant, campaign, str(uuid.uuid4())))
        admin.commit()
        worker = db.image_worker_connection()
        try:
            with worker.cursor() as cur:
                cur.execute("SELECT current_user,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication FROM pg_roles WHERE rolname=current_user")
                assert cur.fetchone() == ('ceopro_image_worker', False, False, False, False, False, False)
                cur.execute("SELECT has_table_privilege(current_user,'public.products','SELECT'),has_table_privilege(current_user,'public.image_workers','INSERT'),has_function_privilege(current_user,'public.claim_image_generation_job(text,integer)','EXECUTE'),has_function_privilege('ceopro_app','public.image_worker_claim(text,integer)','EXECUTE')")
                assert cur.fetchone() == (False, False, False, False)
                cur.execute("SELECT has_any_column_privilege(current_user,'public.image_generation_jobs','UPDATE'),has_function_privilege(current_user,'public.image_generation_capacity(integer,integer)','EXECUTE'),has_function_privilege('ceopro_app','public.image_job_heartbeat(uuid,text)','EXECUTE'),has_function_privilege('ceopro_app','public.image_worker_heartbeat(text,text,integer,integer)','EXECUTE')")
                assert cur.fetchone() == (False, False, False, False)
            worker.rollback()
            image_jobs.worker_heartbeat(worker, worker_id, 'test-host', 1)
            assert image_jobs.claim(worker, worker_id)[:2] == (job, tenant)
            with admin.cursor() as cur:
                cur.execute("UPDATE image_generation_jobs SET heartbeat_at='2000-01-01' WHERE job_id=%s", (job,))
            admin.commit()
            with worker.cursor() as cur:
                cur.execute('SELECT public.image_job_heartbeat(%s,%s)', (job, 'different-worker'))
                assert cur.fetchone() == (False,)
                cur.execute('SELECT public.image_job_heartbeat(%s,%s)', (job, worker_id))
                assert cur.fetchone() == (True,)
            worker.commit()
            with worker.cursor() as cur:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute('SELECT * FROM public.products')
            worker.rollback()
        finally:
            worker.close()
        with admin.cursor() as cur:
            cur.execute("SELECT status,heartbeat_at > '2000-01-01'::timestamptz FROM image_generation_jobs WHERE job_id=%s", (job,))
            assert cur.fetchone() == ('RUNNING', True)
            cur.execute("SELECT servers FROM image_workers WHERE worker_id=%s", (worker_id,))
            assert cur.fetchone() == (1,)
            cur.execute('DELETE FROM companies WHERE tenant_id=%s', (tenant,))
            cur.execute('DELETE FROM image_workers WHERE worker_id=%s', (worker_id,))


def test_image_worker_process_starts_with_restricted_identity():
    from src.ai import db
    with psycopg2.connect(DATABASE_URL) as admin:
        with admin.cursor() as cur:
            cur.execute("SELECT count(*) FROM image_generation_jobs WHERE status IN ('QUEUED','RUNNING')")
            assert cur.fetchone()[0] == 0, 'startup test requires an empty disposable queue'
        env = dict(os.environ, DATABASE_URL=db._app_database_url(), MARKETING_IMAGE_WORKER_POLL_SECONDS='0.1',
                   MARKETING_IMAGE_WORKER_HEARTBEAT_SECONDS='0.2')
        process = subprocess.Popen([sys.executable, '-m', 'src.ai.marketing.image_worker', '--threads', '1'],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 20
            found = False
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    pids = [process.pid, *(p.pid for p in psutil.Process(process.pid).children(recursive=True))]
                except psutil.Error:
                    pids = [process.pid]
                with admin.cursor() as cur:
                    cur.execute('SELECT EXISTS (SELECT 1 FROM image_workers WHERE worker_id LIKE ANY(%s))',
                                ([f'%:{pid}' for pid in pids],))
                    found = cur.fetchone()[0]
                admin.rollback()
                if found:
                    break
                time.sleep(.2)
            assert found, 'worker did not publish its heartbeat'
            time.sleep(.5)
        finally:
            process.terminate()
            output = process.communicate(timeout=10)[0].decode('utf-8', errors='replace')
        assert 'permission denied' not in output.lower()
        assert 'claim failed' not in output.lower()
        assert 'heartbeat failed' not in output.lower()
