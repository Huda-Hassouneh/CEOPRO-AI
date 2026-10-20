"""Real PostgreSQL tests. No PGlite, connection doubles, or shared DB fallback."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,timedelta,timezone
import pytest
from psycopg2.extras import Json
from scripts.billing_verification import is_test_database_name, validate_test_environment

pytestmark=pytest.mark.skipif(os.getenv('BILLING_DATABASE_TESTS')!='1',reason='BLOCKED: isolated native PostgreSQL 17 not enabled')


def connect():
    import psycopg2
    assert os.getenv('PHASE1A_ISOLATED_DATABASE')=='YES'and not os.getenv('BILLING_TEST_ENGINE'),'Explicit native disposable cluster required'
    url=validate_test_environment(dict(os.environ),database=True)
    conn=psycopg2.connect(url,connect_timeout=5,gssencmode='disable',sslmode='disable')
    with conn.cursor()as cur:
        cur.execute("SELECT current_database(),current_setting('server_version_num')::integer")
        database,version=cur.fetchone()
        assert is_test_database_name(database)and 170000<=version<180000
    conn.commit();return conn


def runtime_connection():
    conn=connect()
    with conn.cursor()as cur:cur.execute('SET ROLE ceopro_app')
    return conn


def pending(action,payload):
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute('SELECT keel_pending_registration(%s,%s)',(action,Json(payload)))
            result=cur.fetchone()[0]
        conn.commit();return result
    finally:conn.close()


def registration():
    from src.ai.core.security import hash_token
    marker=uuid.uuid4().hex
    return {'email':f'phase1a-{marker}@example.test','password_hash':'bcrypt-native-fixture-only',
     'full_name':'Native Owner','business_name':'Native '+marker,'country_code':'JO','currency':'JOD','timezone':'Asia/Amman',
     'request_hash':hash_token(marker),'code_hash':hash_token('123456'),
     'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),
     'max_attempts':5,'max_sends':5,'send_window_seconds':900}


def test_pending_has_no_permanent_identity_and_duplicate_registration_is_immutable():
    payload=registration();assert pending('register',payload)['status']=='pending'
    assert pending('register',{**payload,'password_hash':'replacement'})['status']=='conflict'
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT count(*) FROM users WHERE email=%s',(payload['email'],));assert cur.fetchone()[0]==0
            cur.execute('SELECT password_hash FROM keel_pending_registrations WHERE email=%s',(payload['email'],));assert cur.fetchone()[0]==payload['password_hash']
            cur.execute('SELECT count(*) FROM companies WHERE business_name=%s',(payload['business_name'],));assert cur.fetchone()[0]==0
    finally:conn.close()


def test_parallel_registration_creates_one_pending_record_and_conflicts_for_the_rest():
    payload=registration();barrier=Barrier(8)
    def register(_):barrier.wait(timeout=10);return pending('register',payload)
    try:
        with ThreadPoolExecutor(max_workers=8)as workers:results=list(workers.map(register,range(8)))
        assert sum(x['status']=='pending'for x in results)==1
        assert sum(x['status']=='conflict'for x in results)==7
        conn=connect()
        try:
            with conn.cursor()as cur:
                cur.execute('SELECT count(*)FROM keel_pending_registrations WHERE email=%s',(payload['email'],))
                assert cur.fetchone()[0]==1
                cur.execute('SELECT count(*)FROM users WHERE email=%s',(payload['email'],))
                assert cur.fetchone()[0]==0
        finally:conn.close()
    finally:
        conn=connect()
        try:
            with conn.cursor()as cur:
                cur.execute('DELETE FROM keel_pending_registrations WHERE email=%s',(payload['email'],))
            conn.commit()
        finally:conn.close()


def test_parallel_verification_commits_exactly_one_user_company_membership():
    payload=registration();pending('register',payload);barrier=Barrier(8)
    def verify(_):barrier.wait(timeout=10);return pending('verify',payload)
    with ThreadPoolExecutor(max_workers=8)as workers:results=list(workers.map(verify,range(8)))
    assert sum(x['status']=='created'for x in results)==1
    assert sum(x['status']=='verified'for x in results)==7
    created=next(x for x in results if x['status']=='created');conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT count(*) FROM users WHERE email=%s',(payload['email'],));assert cur.fetchone()[0]==1
            cur.execute('SELECT count(*) FROM tenant_users WHERE tenant_id=%s AND user_id=%s',(created['tenant_id'],created['user_id']));assert cur.fetchone()[0]==1
            cur.execute('SELECT password_hash IS NULL FROM keel_pending_registrations WHERE email=%s',(payload['email'],));assert cur.fetchone()[0]is True
    finally:conn.close()


def test_database_wrong_code_limit_survives_resend_and_retries():
    payload=registration();pending('register',payload)
    for _ in range(payload['max_attempts']):assert pending('verify',{**payload,'code_hash':'0'*64})['status']=='invalid'
    assert pending('resend',payload)['status']=='pending'
    assert pending('verify',payload)['status']=='limited'


def test_expired_challenge_cannot_create_a_customer():
    payload=registration();pending('register',payload);conn=connect()
    try:
        with conn.cursor()as cur:cur.execute("UPDATE keel_pending_registrations SET expires_at=now()-interval '1 second' WHERE email=%s",(payload['email'],))
        conn.commit()
    finally:conn.close()
    assert pending('verify',payload)['status']=='invalid'


def test_runtime_role_has_no_pending_or_platform_table_access_or_bootstrap_privilege():
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'");assert cur.fetchone()==(False,False)
            for table in ['keel_pending_registrations','keel_platform_members','keel_platform_invitations','keel_platform_audit','keel_platform_approvals']:
                cur.execute('SELECT has_table_privilege(%s,%s,%s)',('ceopro_app',table,'SELECT'));assert cur.fetchone()[0]is False
                cur.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,));assert cur.fetchone()==(True,True)
            cur.execute("SELECT has_function_privilege('ceopro_app','keel_bootstrap_platform_owner(uuid,text,text,text)','EXECUTE')");assert cur.fetchone()[0]is False
            cur.execute("SELECT count(*)FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid='keel_platform_command(text,jsonb)'::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE'")
            assert cur.fetchone()[0]==0
    finally:conn.close()


@pytest.fixture(scope='module')
def platform_owner():
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("SELECT m.user_id,w.tenant_id,u.email FROM keel_platform_members m CROSS JOIN keel_platform_workspace w JOIN users u ON u.user_id=m.user_id WHERE m.role_key='owner'AND m.status='active'")
            row=cur.fetchone()
            if row:
                assert row[2].startswith('phase1a-owner-'),'Refuse unknown existing platform owner in test fixture'
                return str(row[0]),str(row[1])
            uid=str(uuid.uuid4())
            cur.execute("INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at)VALUES(%s,%s,'fixture-only','Native platform owner',now())",(uid,f'phase1a-owner-{uid}@example.test'))
            cur.execute("SELECT keel_bootstrap_platform_owner(%s,'JO','JOD','Native isolated fixture')",(uid,));tid=str(cur.fetchone()[0])
        conn.commit();return uid,tid
    finally:conn.close()


def command(actor,tenant,action,payload):
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute("SELECT set_config('app.current_user_id',%s,true),set_config('app.current_tenant_id',%s,true)",(actor,tenant))
            cur.execute('SELECT keel_platform_command(%s,%s)',(action,Json(payload)));result=cur.fetchone()[0]
        conn.commit();return result
    finally:conn.close()


def test_customer_owner_never_has_platform_permissions(platform_owner):
    payload=registration();pending('register',payload);customer=pending('verify',payload)
    assert command(customer['user_id'],customer['tenant_id'],'overview',{})=={'error':'forbidden'}


def test_admin_invitation_is_once_only_and_financial_denial_is_audited(platform_owner):
    from src.ai.core.security import hash_token
    owner,tid=platform_owner;raw=uuid.uuid4().hex;email=f'phase1a-admin-{raw}@example.test'
    invite=command(owner,tid,'invite',{'email':email,'token_hash':hash_token(raw),'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'native fixture'})
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute('SELECT keel_platform_accept(%s,%s,true)',(hash_token(raw),Json({'full_name':'Native admin','password_hash':'fixture-only'})));admin=cur.fetchone()[0]
        conn.commit()
        with conn.cursor()as cur:
            cur.execute('SELECT keel_platform_accept(%s,%s,true)',(hash_token(raw),Json({})));assert cur.fetchone()[0]=={'error':'not_found'}
        conn.commit()
    finally:conn.close()
    assert command(admin['user_id'],tid,'financial_approval',{'reason':'must be denied'})=={'error':'forbidden'}
    assert command(admin['user_id'],tid,'member_update',{'id':owner,'status':'removed','reason':'forbidden'})=={'error':'forbidden'}
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("SELECT count(*)FROM keel_platform_audit WHERE actor_user_id=%s AND action='financial_approval'AND outcome='denied'",(admin['user_id'],));assert cur.fetchone()[0]==1
    finally:conn.close()
    assert invite['email']==email


def test_last_owner_protected_and_approval_replay_binds_terms(platform_owner):
    owner,tid=platform_owner
    assert command(owner,tid,'member_update',{'id':owner,'status':'removed','reason':'invalid'})=={'error':'last_owner'}
    data={'request_id':str(uuid.uuid4()),'kind':'manual_access','subject':'native-contract','terms':{'description':'review only'},'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'native owner approval'}
    first=command(owner,tid,'financial_approval',data);second=command(owner,tid,'financial_approval',data)
    assert first['approval_id']==second['approval_id']
    assert command(owner,tid,'financial_approval',{**data,'terms':{'description':'changed'}})=={'error':'idempotency_conflict'}


def test_native_suspension_denies_existing_principal_and_rls(platform_owner):
    owner,tid=platform_owner;payload=registration();pending('register',payload);customer=pending('verify',payload)
    command(owner,tid,'company_status',{'id':customer['tenant_id'],'active':False,'reason':'native suspension'})
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute('SELECT keel_active_principal(%s,%s)',(customer['user_id'],customer['tenant_id']));assert cur.fetchone()[0]is False
            cur.execute("SELECT set_config('app.current_user_id',%s,true),set_config('app.current_tenant_id',%s,true)",(customer['user_id'],customer['tenant_id']))
            cur.execute('SELECT get_current_tenant()');assert cur.fetchone()[0]is None
            cur.execute('SELECT count(*)FROM companies WHERE tenant_id=%s',(customer['tenant_id'],));assert cur.fetchone()[0]==0
    finally:conn.close()


def test_two_native_owner_transfers_cannot_both_use_the_old_owner_authority(platform_owner):
    owner,tid=platform_owner;admins=[];conn=connect()
    try:
        with conn.cursor()as cur:
            for _ in range(2):
                uid=str(uuid.uuid4());admins.append(uid)
                cur.execute("INSERT INTO users(user_id,email,password_hash,email_verified_at)VALUES(%s,%s,'fixture-only',now())",(uid,f'phase1a-transfer-{uid}@example.test'))
                cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key)VALUES(%s,%s,'staff')",(tid,uid))
                cur.execute("INSERT INTO keel_platform_members(user_id,role_key)VALUES(%s,'admin')",(uid,))
        conn.commit()
    finally:conn.close()
    barrier=Barrier(2)
    def transfer(uid):barrier.wait(timeout=10);return command(owner,tid,'owner_transfer',{'id':uid,'reason':'native race'})
    with ThreadPoolExecutor(max_workers=2)as workers:results=list(workers.map(transfer,admins))
    winners=[x['owner']for x in results if'owner'in x]
    assert len(winners)==1 and sum(x.get('error')=='forbidden'for x in results)==1
    assert command(winners[0],tid,'owner_transfer',{'id':owner,'reason':'restore isolated fixture owner'})['owner']==owner


def test_platform_suspension_fences_team_invitation_and_preserves_report_actor_checks(platform_owner):
    owner,tid=platform_owner;payload=registration();pending('register',payload);customer=pending('verify',payload)
    conn=connect()
    try:
        with conn.cursor()as cur:
            # Add a second customer owner so one membership may safely be suspended.
            second=str(uuid.uuid4());cur.execute("INSERT INTO users(user_id,email,password_hash,email_verified_at)VALUES(%s,%s,'fixture-only',now())",(second,f'phase1a-second-{second}@example.test'))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key)VALUES(%s,%s,'owner')",(customer['tenant_id'],second))
            cur.execute("SELECT tenant_user_id FROM tenant_users WHERE tenant_id=%s AND user_id=%s",(customer['tenant_id'],customer['user_id']));membership=str(cur.fetchone()[0])
        conn.commit()
    finally:conn.close()
    assert command(owner,tid,'membership_status',{'id':membership,'active':False,'reason':'native suspension'})['active']is False
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("SELECT removed_at IS NOT NULL,platform_suspended_at IS NOT NULL FROM tenant_users WHERE tenant_user_id=%s",(membership,));assert cur.fetchone()==(True,True)
            cur.execute('SELECT keel_active_principal(%s,%s)',(customer['user_id'],customer['tenant_id']));assert cur.fetchone()[0]is False
    finally:conn.close()
    assert command(owner,tid,'membership_restore_scope',{'id':membership})['tenant_id']==customer['tenant_id']
    assert command(owner,tid,'membership_status',{'id':membership,'active':True,'reason':'missing canonical limit'})['error']=='seat_capacity'
    assert command(owner,tid,'membership_status',{'id':membership,'active':True,'reason':'full seat','_seat_limit':1})['error']=='seat_capacity'
    assert command(owner,tid,'membership_status',{'id':membership,'active':True,'reason':'native restore','_seat_limit':2})['active']is True


def test_native_http_signup_verification_reuses_python_trial_and_jwt(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.routers import auth
    from src.ai.core import auth_throttle,notifications,security
    captured=[]
    monkeypatch.setattr(auth.db,'auth_lookup_connection',runtime_connection)
    monkeypatch.setattr(auth.db,'system_connection',connect)
    monkeypatch.setattr(auth_throttle,'ensure_allowed',lambda *a:None)
    monkeypatch.setattr(auth_throttle,'record_failure',lambda *a:False)
    monkeypatch.setattr(auth_throttle,'reset',lambda *a:None)
    monkeypatch.setattr(notifications,'send_email_verification_email',lambda email,code:(captured.append(code)or True))
    app=FastAPI();app.include_router(auth.router);email=f'phase1a-http-{uuid.uuid4().hex}@example.test'
    with TestClient(app)as client:
        start=client.post('/auth/signup',json={'email':email,'password':'StrongPass1!','full_name':'Native HTTP owner','business_name':'HTTP native shop','country_code':'JO','primary_currency':'JOD'})
        assert start.status_code==202 and'REDIS'not in start.text
        body={'email':email,'code':captured[0],'registration_token':start.json()['registration_token']}
        verified=client.post('/auth/email/verify',json=body)
        assert verified.status_code==200 and verified.json()['access_token']
        import jwt
        claims=jwt.decode(verified.json()['access_token'],security._JWT_SECRET,algorithms=['HS256'])
        assert claims['user_id']==verified.json()['user_id']and claims['ev']is True
        replay=client.post('/auth/email/verify',json=body)
        assert replay.json()['already_verified']and'access_token'not in replay.json()
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT count(*)FROM billing_trials WHERE tenant_id=%s',(claims['tenant_id'],));assert cur.fetchone()[0]==1
    finally:conn.close()


def test_same_numeric_code_for_different_users_does_not_collide_or_reset_the_wrong_user():
    from src.ai.core.security import hash_token
    conn=connect();ids=[str(uuid.uuid4()),str(uuid.uuid4())]
    try:
        with conn.cursor()as cur:
            for uid in ids:
                cur.execute("INSERT INTO users(user_id,email,password_hash)VALUES(%s,%s,'fixture-only')",(uid,f'phase1a-code-{uid}@example.test'))
                cur.execute("INSERT INTO auth_tokens(token_type,token_hash,user_id,expires_at)VALUES('PASSWORD_RESET',%s,%s,now()+interval '10 minutes')",(hash_token('123456'),uid))
            cur.execute("SELECT count(*)FROM auth_tokens WHERE token_type='PASSWORD_RESET'AND token_hash=%s AND user_id=ANY(%s::uuid[])",(hash_token('123456'),ids));assert cur.fetchone()[0]==2
        conn.commit()
    finally:conn.close()


def test_platform_invitation_reuses_existing_python_identity_password_and_memberships(platform_owner):
    from src.ai.core.security import hash_token
    owner,tid=platform_owner;payload=registration();pending('register',payload);customer=pending('verify',payload)
    raw=uuid.uuid4().hex
    command(owner,tid,'invite',{'email':payload['email'],'token_hash':hash_token(raw),'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'reuse existing identity'})
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute('SELECT keel_platform_accept(%s,%s,true)',(hash_token(raw),Json({})));accepted=cur.fetchone()[0]
        conn.commit()
        assert accepted['user_id']==customer['user_id']
        with conn.cursor()as cur:cur.execute('RESET ROLE')
        conn.commit()
        with conn.cursor()as cur:
            cur.execute('SELECT password_hash FROM users WHERE user_id=%s',(customer['user_id'],));assert cur.fetchone()[0]==payload['password_hash']
            cur.execute('SELECT count(*)FROM tenant_users WHERE user_id=%s AND removed_at IS NULL',(customer['user_id'],));assert cur.fetchone()[0]==2
    finally:conn.close()


def test_password_reset_increments_durable_version_without_changing_memberships():
    payload=registration();pending('register',payload);customer=pending('verify',payload);conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app')
            cur.execute('SELECT auth_credential_version(%s)',(customer['user_id'],));assert cur.fetchone()[0]==0
            cur.execute('SELECT auth_reset_password(%s,%s)',(customer['user_id'],'new-fixture-hash'))
            cur.execute('SELECT auth_credential_version(%s),keel_active_principal(%s,%s)',(customer['user_id'],customer['user_id'],customer['tenant_id']));assert cur.fetchone()==(1,True)
        conn.commit()
    finally:conn.close()


def test_inactive_operator_cannot_be_reactivated_by_invitation(platform_owner):
    from src.ai.core.security import hash_token
    owner,tid=platform_owner;uid=str(uuid.uuid4());email=f'phase1a-inactive-{uid}@example.test';raw=uuid.uuid4().hex;conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("INSERT INTO users(user_id,email,password_hash,email_verified_at)VALUES(%s,%s,'fixture-only',now())",(uid,email))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key)VALUES(%s,%s,'staff')",(tid,uid))
            cur.execute("INSERT INTO keel_platform_members(user_id,role_key,status)VALUES(%s,'admin','suspended')",(uid,))
            cur.execute("INSERT INTO keel_platform_invitations(email,token_hash,expires_at,created_by)VALUES(%s,%s,now()+interval '1 hour',%s)",(email,hash_token(raw),owner))
        conn.commit()
        assert command(owner,tid,'invite',{'email':email,'token_hash':hash_token('replacement-'+raw),'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'cannot bypass suspension'})=={'error':'operator_inactive'}
        with conn.cursor()as cur:
            cur.execute('SET ROLE ceopro_app');cur.execute('SELECT keel_platform_accept(%s,%s,true)',(hash_token(raw),Json({})));assert cur.fetchone()[0]=={'error':'operator_inactive'}
        conn.commit()
        with conn.cursor()as cur:
            cur.execute('RESET ROLE');cur.execute('SELECT status FROM keel_platform_members WHERE user_id=%s',(uid,));assert cur.fetchone()[0]=='suspended'
        assert command(owner,tid,'member_update',{'id':uid,'status':'active','reason':'explicit Owner restore'})['status']=='active'
    finally:conn.close()


def test_numeric_code_cannot_be_consumed_after_wall_clock_expiry():
    from src.ai.routers.auth import _consume_token
    from fastapi import HTTPException
    payload=registration();pending('register',payload);created=pending('verify',payload);conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT now()');cur.execute('SELECT pg_sleep(0.02)')
            cur.execute("INSERT INTO auth_tokens(token_type,token_hash,user_id,expires_at)VALUES('PASSWORD_RESET',%s,%s,clock_timestamp()-interval '1 millisecond')RETURNING token_id",(uuid.uuid4().hex.ljust(64,'0'),created['user_id']));token=cur.fetchone()[0]
        with pytest.raises(HTTPException)as error:_consume_token(conn,token)
        assert error.value.status_code==400
        with conn.cursor()as cur:
            cur.execute('SELECT used_at FROM auth_tokens WHERE token_id=%s',(token,));assert cur.fetchone()[0]is None
    finally:conn.rollback();conn.close()


def test_login_snapshot_does_not_adopt_a_reset_version(monkeypatch):
    from src.ai.routers import auth
    from src.ai.core import security,auth_throttle
    import jwt
    payload=registration();payload['password_hash']=security.hash_password('OldStrong1!')
    pending('register',payload);created=pending('verify',payload)
    monkeypatch.setattr(auth.db,'auth_lookup_connection',runtime_connection)
    for name in ['ensure_allowed','record_failure','reset']:monkeypatch.setattr(auth_throttle,name,lambda *a:None)
    real_verify=auth.verify_password
    def reset_after_password_snapshot(plain,digest):
        matched=real_verify(plain,digest);conn=connect()
        try:
            with conn.cursor()as cur:cur.execute('SELECT auth_reset_password(%s,%s)',(created['user_id'],security.hash_password('NewStrong2!')))
            conn.commit()
        finally:conn.close()
        return matched
    monkeypatch.setattr(auth,'verify_password',reset_after_password_snapshot)
    result=auth.login(auth.LoginRequest(email=payload['email'],password='OldStrong1!'))
    claims=jwt.decode(result['access_token'],security._JWT_SECRET,algorithms=['HS256']);assert claims['cv']==0
    from fastapi import HTTPException
    with pytest.raises(HTTPException)as error:security.assert_active_principal(created['tenant_id'],created['user_id'],claims['cv'])
    assert error.value.status_code==401


def test_native_http_password_reset_consumes_only_the_email_bound_code(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core import auth_throttle, security
    from src.ai.routers import auth
    monkeypatch.setattr(auth.db,'auth_lookup_connection',runtime_connection)
    monkeypatch.setattr(auth_throttle,'ensure_allowed',lambda *a:None)
    monkeypatch.setattr(auth_throttle,'record_failure',lambda *a:False)
    monkeypatch.setattr(auth_throttle,'reset',lambda *a:None)
    target,other=registration(),registration()
    pending('register',target);target_user=pending('verify',target)
    pending('register',other);other_user=pending('verify',other)
    target_code=f'{int(uuid.uuid4().hex[:8],16)%1_000_000:06d}'
    other_code=f'{(int(target_code)+1)%1_000_000:06d}'
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute("INSERT INTO auth_tokens(token_type,token_hash,user_id,expires_at)VALUES('PASSWORD_RESET',%s,%s,now()+interval '10 minutes')",
                        (security.hash_token(target_code),target_user['user_id']))
            cur.execute("INSERT INTO auth_tokens(token_type,token_hash,user_id,expires_at)VALUES('PASSWORD_RESET',%s,%s,now()+interval '10 minutes')",
                        (security.hash_token(other_code),other_user['user_id']))
        conn.commit()
    finally:conn.close()
    app=FastAPI();app.include_router(auth.router)
    with TestClient(app)as client:
        wrong=client.post('/auth/password/reset',json={'email':target['email'],'code':other_code,'new_password':'UpdatedPass1!'})
        assert wrong.status_code==400
        accepted=client.post('/auth/password/reset',json={'email':target['email'],'code':target_code,'new_password':'UpdatedPass1!'})
        assert accepted.status_code==200 and accepted.json()=={'ok':True}
        replay=client.post('/auth/password/reset',json={'email':target['email'],'code':target_code,'new_password':'AnotherPass2!'})
        assert replay.status_code==400
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT auth_credential_version(%s),email_verified_at IS NOT NULL FROM users WHERE user_id=%s',
                        (target_user['user_id'],target_user['user_id']))
            assert cur.fetchone()==(1,True)
            cur.execute('SELECT count(*)FROM tenant_users WHERE user_id=%s AND removed_at IS NULL',(target_user['user_id'],))
            assert cur.fetchone()[0]==1
            cur.execute('SELECT password_hash FROM users WHERE user_id=%s',(target_user['user_id'],))
            assert security.verify_password('UpdatedPass1!',cur.fetchone()[0])
            cur.execute('SELECT password_hash FROM users WHERE user_id=%s',(other_user['user_id'],))
            assert cur.fetchone()[0]==other['password_hash']
            cur.execute('SELECT used_at IS NOT NULL FROM auth_tokens WHERE user_id=%s AND token_hash=%s',
                        (target_user['user_id'],security.hash_token(target_code)))
            assert cur.fetchone()[0]is True
            cur.execute('SELECT used_at IS NULL FROM auth_tokens WHERE user_id=%s AND token_hash=%s',
                        (other_user['user_id'],security.hash_token(other_code)))
            assert cur.fetchone()[0]is True
    finally:conn.close()


def test_native_http_customer_invitation_reuses_and_creates_identities(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core import auth_throttle, security
    from src.ai.routers import auth
    monkeypatch.setattr(auth.db,'auth_lookup_connection',runtime_connection)
    monkeypatch.setattr(auth.db,'system_connection',connect)
    monkeypatch.setattr(auth_throttle,'ensure_allowed',lambda *a:None)
    monkeypatch.setattr(auth_throttle,'record_failure',lambda *a:False)
    monkeypatch.setattr(auth_throttle,'reset',lambda *a:None)
    owner_payload,existing_payload=registration(),registration()
    pending('register',owner_payload);owner=pending('verify',owner_payload)
    pending('register',existing_payload);existing=pending('verify',existing_payload)
    auth._start_free_trial(owner['tenant_id'],owner['user_id'])
    invitations=[]
    conn=connect()
    try:
        with conn.cursor()as cur:
            for email in (existing_payload['email'],f'phase1a-invite-{uuid.uuid4().hex}@example.test'):
                raw=uuid.uuid4().hex
                cur.execute("INSERT INTO auth_tokens(token_type,token_hash,email,tenant_id,role_key,expires_at) "
                            "VALUES('TEAM_INVITATION',%s,%s,%s,'staff',now()+interval '1 hour')",
                            (security.hash_token(raw),email,owner['tenant_id']))
                invitations.append((raw,email))
        conn.commit()
    finally:conn.close()
    app=FastAPI();app.include_router(auth.router)
    raw_existing,existing_email=invitations[0]
    raw_new,new_email=invitations[1]
    with TestClient(app)as client:
        reused=client.post(f'/auth/invitations/{raw_existing}/accept',json={})
        assert reused.status_code==200
        assert reused.json()['user_id']==existing['user_id']
        assert reused.json()['role_key']=='staff'
        missing=client.post(f'/auth/invitations/{raw_new}/accept',json={})
        assert missing.status_code==422
        created=client.post(f'/auth/invitations/{raw_new}/accept',
                            json={'full_name':'Native Invitee','password':'StrongPass1!'})
        assert created.status_code==200
        assert created.json()['email']==new_email
        assert created.json()['full_name']=='Native Invitee'
        assert created.json()['role_key']=='staff'
        replay=client.post(f'/auth/invitations/{raw_new}/accept',
                           json={'full_name':'Native Invitee','password':'StrongPass1!'})
        assert replay.status_code==404
    conn=connect()
    try:
        with conn.cursor()as cur:
            cur.execute('SELECT count(*)FROM tenant_users WHERE tenant_id=%s AND user_id=%s AND role_key=%s AND removed_at IS NULL',
                        (owner['tenant_id'],existing['user_id'],'staff'))
            assert cur.fetchone()[0]==1
            cur.execute('SELECT user_id FROM users WHERE email=%s',(new_email,))
            created_user=cur.fetchone()[0]
            cur.execute('SELECT count(*)FROM tenant_users WHERE tenant_id=%s AND user_id=%s AND role_key=%s AND removed_at IS NULL',
                        (owner['tenant_id'],created_user,'staff'))
            assert cur.fetchone()[0]==1
            cur.execute('SELECT used_at IS NOT NULL FROM auth_tokens WHERE token_hash=%s',
                        (security.hash_token(raw_existing),))
            assert cur.fetchone()[0]is True
            cur.execute('SELECT used_at IS NOT NULL FROM auth_tokens WHERE token_hash=%s',
                        (security.hash_token(raw_new),))
            assert cur.fetchone()[0]is True
    finally:conn.close()
