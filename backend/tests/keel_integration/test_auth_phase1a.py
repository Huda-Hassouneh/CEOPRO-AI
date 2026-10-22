from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import jwt
import pytest
from fastapi import HTTPException
from src.ai.core import pending_registration as pending, security
from src.ai.routers import auth

PAYLOAD={'email':'New.Owner+trial@example.test','password':'StrongPass1!','full_name':'New owner','business_name':'New business','country_code':'jo','primary_currency':'jod'}


def test_signup_only_stages_and_never_issues_a_session(api,monkeypatch):
    calls=[]
    monkeypatch.setattr(pending,'_call',lambda action,payload:(calls.append((action,payload))or{'status':'pending'}))
    monkeypatch.setattr(pending.notifications,'send_email_verification_email',lambda *a:True)
    monkeypatch.setattr(auth,'_insert_company',lambda *a:pytest.fail('Permanent company created before verification'))
    monkeypatch.setattr(auth,'_start_free_trial',lambda *a:pytest.fail('Trial started before verification'))
    result=api.post('/auth/signup',json=PAYLOAD)
    assert result.status_code==202
    data=result.json();assert data['status']=='pending_verification' and data['delivery']=='sent'
    assert not({'access_token','user_id','tenant_id'}&data.keys())
    action,body=calls[0];assert action=='register' and body['email']=='new.owner+trial@example.test'
    assert body['country_code']=='JO' and body['currency']=='JOD'
    assert body['request_hash']==security.hash_token(data['registration_token'])
    assert body['password_hash']!=PAYLOAD['password'] and security.verify_password(PAYLOAD['password'],body['password_hash'])


@pytest.mark.parametrize('changes',[{'password':'weak'},{'country_code':'J'},{'email':'bad'},{'business_name':''}])
def test_invalid_signup_never_reaches_persistence(api,monkeypatch,changes):
    monkeypatch.setattr(pending,'_call',lambda *a:pytest.fail('Invalid registration persisted'))
    assert api.post('/auth/signup',json={**PAYLOAD,**changes}).status_code==422


def test_duplicate_registration_preserves_existing_pending_credentials(api,monkeypatch):
    monkeypatch.setattr(pending,'_call',lambda *a:{'status':'conflict'})
    monkeypatch.setattr(pending.notifications,'send_email_verification_email',lambda *a:pytest.fail('Duplicate replaced the code'))
    assert api.post('/auth/signup',json=PAYLOAD).status_code==409


@pytest.mark.parametrize('delivery',[False,RuntimeError('SMTP unavailable')])
def test_email_failure_is_truthful_and_does_not_create_a_permanent_account(api,monkeypatch,delivery):
    monkeypatch.setattr(pending,'_call',lambda *a:{'status':'pending'})
    def send(*args):
        if isinstance(delivery,Exception):raise delivery
        return delivery
    monkeypatch.setattr(pending.notifications,'send_email_verification_email',send)
    result=api.post('/auth/signup',json=PAYLOAD)
    assert result.status_code==202 and result.json()['delivery']=='unavailable'
    assert 'registration_token'in result.json() and 'access_token'not in result.json()


def test_verified_registration_uses_existing_session_and_trial_authorities(api,monkeypatch):
    result={'status':'created','created':True,'tenant_id':'t','user_id':'u','business_name':'Shop','full_name':'Owner','email':'a@example.test'}
    monkeypatch.setattr(pending,'_call',lambda *a:result)
    calls=[];monkeypatch.setattr(auth,'_start_free_trial',lambda *a:calls.append(a))
    monkeypatch.setattr(auth,'_session',lambda *a:{'access_token':'python-issued','tenant_id':'t','user_id':'u'})
    response=api.post('/auth/email/verify',json={'email':'a@example.test','code':'123456','registration_token':'secret'})
    assert response.status_code==200 and response.json()['access_token']=='python-issued' and calls==[('t','u')]


def test_duplicate_verification_does_not_issue_another_session_or_trial(api,monkeypatch):
    monkeypatch.setattr(pending,'_call',lambda *a:{'status':'verified','created':False})
    monkeypatch.setattr(auth,'_start_free_trial',lambda *a:pytest.fail('Duplicate trial'))
    monkeypatch.setattr(auth,'_session',lambda *a:pytest.fail('Duplicate token issuance'))
    response=api.post('/auth/email/verify',json={'email':'a@example.test','code':'123456','registration_token':'secret'})
    assert response.status_code==200 and response.json()['already_verified']
    assert 'access_token'not in response.json()


@pytest.mark.parametrize('state,expected',[('invalid',400),('limited',429),('conflict',409)])
def test_expired_wrong_or_exhausted_code_cannot_create_accounts(api,monkeypatch,state,expected):
    monkeypatch.setattr(pending,'_call',lambda *a:{'status':state})
    assert api.post('/auth/email/verify',json={'email':'a@example.test','code':'000000','registration_token':'bad'}).status_code==expected


def test_wrong_code_counter_is_committed_before_http_rejection(monkeypatch):
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=({'status':'invalid'},)
    monkeypatch.setattr(pending.db,'auth_lookup_connection',lambda:conn)
    with pytest.raises(HTTPException):pending.verify('a@example.test','secret','000000')
    conn.commit.assert_called_once();conn.close.assert_called_once();conn.rollback.assert_not_called()


def test_revocation_outage_is_503_not_unrevoked(monkeypatch):
    store=MagicMock();store.exists.side_effect=OSError('redis down')
    monkeypatch.setattr(security,'_revocation_store',lambda:store)
    monkeypatch.setattr(security,'_durable_revocation',lambda *a:(_ for _ in ()).throw(OSError('database unavailable')))
    with pytest.raises(HTTPException)as error:security.is_token_revoked('jti')
    assert error.value.status_code==503 and error.value.headers['X-Auth-Reason']=='revocation-unavailable'


def test_failed_revocation_write_is_not_success(monkeypatch):
    store=MagicMock();store.set.side_effect=OSError('redis down')
    monkeypatch.setattr(security,'_revocation_store',lambda:store)
    with pytest.raises(HTTPException)as error:security.revoke_token('jti',datetime.now(timezone.utc).timestamp()+60)
    assert error.value.status_code==503


def test_protected_request_fails_closed_before_handler_when_revocation_is_unknown(api,monkeypatch,token):
    def unknown(*args,**kwargs):raise HTTPException(503,'Session verification unavailable')
    monkeypatch.setattr(security,'is_token_revoked',unknown)
    monkeypatch.setattr(auth,'_fetch_user_memberships',lambda *a:pytest.fail('Protected handler ran'))
    assert api.get('/auth/workspaces',headers=token).status_code==503


def test_active_principal_is_rechecked_and_unknown_db_fails_closed(monkeypatch):
    monkeypatch.setattr(auth.db,'auth_lookup_connection',lambda:(_ for _ in ()).throw(RuntimeError('DB down')))
    with pytest.raises(HTTPException)as error:security.assert_active_principal('t','u')
    assert error.value.status_code==503


def test_legacy_token_without_jti_receives_stable_revocable_identity(monkeypatch):
    raw=jwt.encode({'tenant_id':'t','user_id':'u','exp':datetime.now(timezone.utc)+timedelta(minutes=5)},security._JWT_SECRET,algorithm='HS256')
    checked=[];monkeypatch.setattr(security,'is_token_revoked',lambda x,**kwargs:(checked.append(x)or False))
    monkeypatch.setattr(security,'assert_active_principal',lambda *a:None)
    ctx=security.get_tenant_context(authorization='Bearer '+raw)
    assert ctx.token_id==checked[0] and ctx.token_id.startswith('legacy:')


def test_registered_email_verification_still_uses_existing_token_authority(api,monkeypatch):
    conn=MagicMock();monkeypatch.setattr(auth.db,'auth_lookup_connection',lambda:conn)
    monkeypatch.setattr(auth,'_active_code_or_reject',lambda *a:{'user_id':'u','token_id':'token'})
    consumed=[];monkeypatch.setattr(auth,'_consume_token',lambda *a:consumed.append(a[1]))
    assert api.post('/auth/email/verify',json={'email':'a@example.test','code':'123456'}).json()=={'ok':True,'email_verified':True}
    assert consumed==['token']


@pytest.mark.parametrize('answer',[None,'0',2])
def test_unverified_revocation_response_fails_closed(monkeypatch,answer):
    store=MagicMock();store.exists.return_value=answer;monkeypatch.setattr(security,'_revocation_store',lambda:store)
    monkeypatch.setattr(security,'_durable_revocation',lambda *a:(_ for _ in ()).throw(OSError('database unavailable')))
    with pytest.raises(HTTPException)as error:security.is_token_revoked('jti')
    assert error.value.status_code==503


def test_unacknowledged_logout_write_is_not_success(monkeypatch):
    store=MagicMock();store.set.return_value=None;monkeypatch.setattr(security,'_revocation_store',lambda:store)
    with pytest.raises(HTTPException)as error:security.revoke_token('jti',None)
    assert error.value.status_code==503


def test_empty_redis_cache_cannot_reinstate_a_durably_revoked_token(monkeypatch):
    store=MagicMock();store.exists.return_value=0
    monkeypatch.setattr(security,'_revocation_store',lambda:store)
    monkeypatch.setattr(security,'_durable_revocation',lambda token,expires=None:True)
    assert security.is_token_revoked('revoked-before-cache-restart')is True


def test_cache_miss_with_unknown_durable_receipt_is_not_permission(monkeypatch):
    store=MagicMock();store.exists.return_value=0
    monkeypatch.setattr(security,'_revocation_store',lambda:store)
    monkeypatch.setattr(security,'_durable_revocation',lambda *a:(_ for _ in ()).throw(OSError('DB unavailable')))
    with pytest.raises(HTTPException)as error:security.is_token_revoked('jti')
    assert error.value.status_code==503


def test_logout_persists_receipt_before_redis_write_and_reports_cache_outage(monkeypatch):
    events=[];store=MagicMock();store.set.side_effect=OSError('Redis unavailable')
    monkeypatch.setattr(security,'_revocation_store',lambda:store)
    monkeypatch.setattr(security,'_durable_revocation',lambda *a:(events.append('durable')or True))
    with pytest.raises(HTTPException):security.revoke_token('jti',None)
    assert events==['durable']and store.set.called


def test_account_code_checks_correct_user_type_and_commits_wrong_attempt(monkeypatch):
    conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value=('receipt','user',security.hash_token('123456'),datetime.now(timezone.utc)+timedelta(minutes=1),0)
    monkeypatch.setattr(auth,'_fetch_user_by_email',lambda *a:('user','hash','Owner','en'))
    assert auth._fetch_active_code(conn,'PASSWORD_RESET','x@example.test','000000')is None
    conn.commit.assert_called_once()
    statements=[x.args[0]for x in cur.execute.call_args_list]
    assert 'user_id=%s'in statements[0]and'FOR UPDATE'in statements[0]
    assert 'failed_attempts=failed_attempts+1'in statements[1]


def test_exhausted_database_code_budget_cannot_be_bypassed_by_redis_outage(monkeypatch):
    conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value=('receipt','user',security.hash_token('123456'),datetime.now(timezone.utc)+timedelta(minutes=1),5)
    monkeypatch.setattr(auth,'_fetch_user_by_email',lambda *a:('user','hash','Owner','en'))
    assert auth._fetch_active_code(conn,'PASSWORD_RESET','x@example.test','123456')is None


def test_reset_and_code_consumption_share_one_commit(api,monkeypatch):
    conn=MagicMock();monkeypatch.setattr(auth.db,'auth_lookup_connection',lambda:conn)
    monkeypatch.setattr(auth,'_active_code_or_reject',lambda *a:{'user_id':'u','token_id':'receipt'})
    response=api.post('/auth/password/reset',json={'email':'x@example.test','code':'123456','new_password':'StrongPass1!'})
    assert response.status_code==200
    conn.commit.assert_called_once()
    sql=[c.args[0]for c in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert any('auth_reset_password'in x for x in sql)and any('RETURNING token_id'in x for x in sql)


def test_new_token_carries_additive_credential_version():
    token,_=security.create_access_token('t','u',credential_version=7)
    claims=jwt.decode(token,security._JWT_SECRET,algorithms=['HS256'])
    assert claims['cv']==7


def test_static_onboarding_choices_are_available_without_market_entitlement(api):
    response=api.get('/onboarding/industries')
    assert response.status_code==200
    assert response.json()['industries']


def test_password_change_invalidates_old_token_without_revoking_account(monkeypatch):
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,1)
    monkeypatch.setattr(auth.db,'auth_lookup_connection',lambda:conn)
    with pytest.raises(HTTPException)as error:security.assert_active_principal('t','u',0)
    assert error.value.status_code==401
    security.assert_active_principal('t','u',1)


@pytest.mark.parametrize('path',['/auth/password/forgot','/auth/email/resend-verification'])
def test_durable_send_limit_does_not_reveal_account_existence(api,monkeypatch,path):
    conn=MagicMock();monkeypatch.setattr(auth.db,'auth_lookup_connection',lambda:conn)
    monkeypatch.setattr(auth,'_fetch_user_by_email',lambda *a:('u','hash','Owner','en'))
    def limited(*a,**kwargs):raise HTTPException(429,'budget exhausted')
    monkeypatch.setattr(auth,'_send_account_code',limited)
    known=api.post(path,json={'email':'known@example.test'})
    monkeypatch.setattr(auth,'_fetch_user_by_email',lambda *a:None)
    unknown=api.post(path,json={'email':'unknown@example.test'})
    assert known.status_code==unknown.status_code==200 and known.json()==unknown.json()
