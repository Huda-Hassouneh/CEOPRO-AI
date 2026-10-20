"""Executable native migration rehearsal. Refuses populated or unacknowledged databases.

Run fresh and populated modes on separate NEW databases in the dedicated Compose cluster.
No database is created/dropped here; no production DSN or engine fallback is accepted.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from urllib.parse import urlsplit
import psycopg2
from scripts import apply_migrations as runner
from scripts.billing_verification import is_test_database_name, validate_test_environment

MIGRATION='20261025000100_integration_principal_permissions.sql'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['fresh','populated'],required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    url=validate_test_environment(dict(os.environ),database=True)
    if (os.getenv('PHASE1A_ISOLATED_DATABASE')!='YES' or not os.getenv('APP_DB_PASSWORD')
            or os.getenv('BILLING_TEST_ENGINE') or urlsplit(url).username!='keel_billing_test_admin'):
        parser.error('Dedicated Compose test admin, explicit isolation acknowledgment, app-role test password and native engine required')
    conn=psycopg2.connect(url,connect_timeout=5,gssencmode='disable',sslmode='disable')
    try:
        with conn.cursor()as cur:
            cur.execute("SELECT current_database(),current_setting('server_version_num')::integer,current_user")
            database,version,owner=cur.fetchone()
            assert is_test_database_name(database)and 170000<=version<180000 and owner=='keel_billing_test_admin'
            cur.execute("SELECT to_regclass('public.companies')");assert cur.fetchone()[0]is None,'Refuse nonempty fixture database'
        conn.commit()
        previous=runner.MIGRATIONS_DIR
        if args.mode=='populated':
            with tempfile.TemporaryDirectory(prefix='keel-pre-phase1a-')as temp:
                historical=Path(temp)
                for source in previous.glob('*.sql'):
                    if source.name!=MIGRATION:shutil.copyfile(source,historical/source.name)
                runner.MIGRATIONS_DIR=historical
                try:baseline=runner.run(conn)
                finally:runner.MIGRATIONS_DIR=previous
            uid,tid=str(uuid.uuid4()),str(uuid.uuid4())
            with conn.cursor()as cur:
                cur.execute("INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at)VALUES(%s,%s,'preserve-existing-hash','Historical user',now())",(uid,f'phase1a-historical-{uid}@example.test'))
                cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency)VALUES(%s,'Historical company','JO','JOD')",(tid,))
                cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key)VALUES(%s,%s,'owner')",(tid,uid))
                cur.execute("INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id,request_fingerprint)VALUES(%s,'monthly_reports','historical-key',CURRENT_DATE,%s,%s)RETURNING request_id",(tid,uid,'0'*64));receipt=str(cur.fetchone()[0])
                for age,code in [(2,'1'*64),(1,'2'*64)]:
                    cur.execute("INSERT INTO auth_tokens(token_type,token_hash,user_id,expires_at,created_at)VALUES('EMAIL_VERIFICATION',%s,%s,now()+interval '1 hour',now()-make_interval(mins=>%s))",(code,uid,age))
            conn.commit()
            applied=runner.run(conn);assert applied==[MIGRATION]
            with conn.cursor()as cur:
                cur.execute('SELECT password_hash,credential_version FROM users WHERE user_id=%s',(uid,));assert cur.fetchone()==('preserve-existing-hash',0)
                cur.execute("SELECT request_id::text,request_fingerprint FROM metered_request_keys WHERE tenant_id=%s AND idempotency_key='historical-key'",(tid,));assert cur.fetchone()==(receipt,'0'*64)
                cur.execute("SELECT token_hash,used_at IS NULL FROM auth_tokens WHERE user_id=%s ORDER BY created_at",(uid,));assert cur.fetchall()==[('1'*64,False),('2'*64,True)]
                cur.execute('SELECT count(*)FROM tenant_users WHERE tenant_id=%s AND user_id=%s AND removed_at IS NULL',(tid,uid));assert cur.fetchone()[0]==1
            conn.commit()
        else:
            baseline=[];applied=runner.run(conn);assert MIGRATION in applied
        repeated=runner.run(conn);assert repeated==[]
        catalog={}
        with conn.cursor()as cur:
            cur.execute("SELECT rolname,rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname IN('ceopro_app','keel_billing_test_admin')")
            catalog['roles']=cur.fetchall()
            cur.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner),c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'AND c.relkind='r'ORDER BY c.relname")
            catalog['tables']=cur.fetchall()
            cur.execute("SELECT tablename,policyname,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='public'ORDER BY tablename,policyname")
            catalog['policies']=cur.fetchall()
            cur.execute("SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig,p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'AND(p.proname LIKE 'keel_%'OR p.proname LIKE 'auth_%'OR p.proname='get_current_tenant')ORDER BY p.proname")
            catalog['functions']=cur.fetchall()
        output={'mode':args.mode,'database':database,'server_version_num':version,'baseline_applied':baseline,'phase_applied':applied,'repeat_applied':repeated,'historical_compatibility':'PASS'if args.mode=='populated'else'not applicable','catalog':catalog,'native_runtime_tests':'Run phase1a_verification --database and integration_review --database separately; this is migration/catalog evidence only'}
        Path(args.output).write_text(json.dumps(output,default=str,indent=2)+'\n')
        print(json.dumps({'mode':args.mode,'applied':len(applied),'repeat_applied':len(repeated),'output':args.output}))
    finally:conn.close()


if __name__=='__main__':main()
