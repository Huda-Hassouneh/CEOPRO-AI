from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from src.ai.core.authorization import require_platform_permission,ORDINARY_ACTIONS,OWNER_ACTIONS
from src.ai.platform import service
from src.ai.routers import platform


@pytest.mark.parametrize('action',sorted(OWNER_ACTIONS))
def test_platform_admin_has_no_exceptional_authority(action):
    with pytest.raises(HTTPException)as e:require_platform_permission('admin',action)
    assert e.value.status_code==403
    require_platform_permission('owner',action)


@pytest.mark.parametrize('role',['staff','manager','accountant','tenant_owner',None])
def test_ordinary_tenant_roles_do_not_grant_platform_authority(role):
    for action in ORDINARY_ACTIONS|OWNER_ACTIONS:
        with pytest.raises(HTTPException):require_platform_permission(role,action)


def test_anonymous_platform_requests_rejected_before_database(api,monkeypatch):
    monkeypatch.setattr(service,'command',lambda *a:pytest.fail('Anonymous reached platform SQL'))
    assert api.get('/platform/overview').status_code==401


def test_tenant_owner_is_not_trusted_from_the_request(api,monkeypatch,token):
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=({'error':'forbidden'},)
    monkeypatch.setattr(service.db,'app_role_connection',lambda *a:conn)
    response=api.get('/platform/overview',headers=token)
    assert response.status_code==403
    conn.commit.assert_called_once() # Retain the SQL function's denied-attempt audit.
    assert 'keel_platform_command'in conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]


def test_management_contract_has_bounded_pagination(api,monkeypatch,token):
    calls=[];monkeypatch.setattr(service,'command',lambda c,a,p:(calls.append((a,p))or[]))
    assert api.get('/platform/users?limit=101',headers=token).status_code==422
    assert api.get('/platform/users?offset=-1',headers=token).status_code==422
    assert api.get('/platform/users?limit=20&offset=40',headers=token).json()=={'items':[]}
    assert calls==[('users',{'limit':20,'offset':40})]


def test_invitation_cannot_create_an_owner_or_arbitrary_permission(api,monkeypatch,token):
    monkeypatch.setattr(service,'invite',lambda *a:pytest.fail('Role escalation reached service'))
    response=api.post('/platform/team/invitations',headers=token,json={'email':'x@example.test','role':'owner','reason':'test'})
    assert response.status_code==422


@pytest.mark.parametrize('reason',['','   '])
def test_privileged_changes_require_reason(api,token,reason):
    assert api.patch('/platform/users/'+str(uuid4())+'/status',headers=token,json={'active':False,'reason':reason}).status_code==422


def test_disabled_or_invalid_member_operation_maps_to_conflict_and_is_audited(api,monkeypatch,token):
    conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchone.return_value=({'error':'last_owner'},)
    monkeypatch.setattr(service.db,'app_role_connection',lambda *a:conn)
    assert api.patch('/platform/team/'+str(uuid4()),headers=token,json={'status':'removed','reason':'offboard'}).status_code==409
    assert 'keel_platform_record_attempt'in cur.execute.call_args[0][0]
    conn.commit.assert_called_once()


def test_invitation_delivery_failure_preserves_retryable_invitation_without_returning_token(monkeypatch):
    monkeypatch.setattr(service,'command',lambda *a:{'invitation_id':'id','email':'x@example.test'})
    monkeypatch.setattr(service.notifications,'send_email',lambda *a:False)
    events=[];monkeypatch.setattr(service,'record_attempt',lambda *a:events.append(a))
    value=service.invite(object(),{'email':'x@example.test','reason':'join'})
    assert value['delivery']=='unavailable' and 'token'not in value and 'token_hash'not in value
    assert events[0][-1]=='delivery_failed'


def test_expired_or_used_invitation_never_issues_session(api,monkeypatch):
    monkeypatch.setattr(service,'invitation',lambda *a:(_ for _ in ()).throw(HTTPException(404,'expired')))
    assert api.post('/platform/invitations/unknown/accept',json={}).status_code==404


def test_approval_uses_identified_actor_and_does_not_invoke_billing_or_provider(api,monkeypatch,token):
    seen=[];monkeypatch.setattr(service,'command',lambda c,a,p:(seen.append((c.user_id,a,p))or{'approval_id':p['request_id']}))
    value={'request_id':str(uuid4()),'kind':'manual_access','subject':'contract-review','terms':{'description':'Owner reviewed only'},'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'reviewed exception'}
    assert api.post('/platform/financial-approvals',headers=token,json=value).status_code==201
    assert seen[0][0].endswith('0002')and seen[0][1]=='financial_approval'and seen[0][2]['terms']==value['terms']


def test_approval_rejects_unspecified_or_expired_terms(api,token):
    value={'request_id':str(uuid4()),'kind':'manual_access','subject':'c','terms':{},'expires_at':datetime.now(timezone.utc).isoformat(),'reason':'review'}
    assert api.post('/platform/financial-approvals',headers=token,json=value).status_code==422


def test_per_workspace_suspension_is_distinct_from_global_account_control(api,monkeypatch,token):
    calls=[];monkeypatch.setattr(service,'command',lambda c,a,p:(calls.append((a,p))or{'active':False}))
    identity=str(uuid4())
    response=api.patch('/platform/memberships/'+identity+'/status',headers=token,json={'active':False,'reason':'workspace review'})
    assert response.status_code==200 and calls==[('membership_status',{'id':identity,'active':False,'reason':'workspace review'})]


def test_platform_workspace_cannot_be_administered_as_an_ordinary_tenant(monkeypatch):
    from src.ai.routers.settings import _require_role
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,)
    with pytest.raises(HTTPException)as error:_require_role(conn,'platform','ordinary-owner',{'owner'})
    assert error.value.status_code==403


def test_operator_cli_never_accepts_a_claimed_owner_uuid_without_a_verified_session(monkeypatch):
    import io
    from scripts import billing_admin
    monkeypatch.setattr('sys.stdin',io.StringIO(''))
    monkeypatch.setattr(billing_admin,'_connect',lambda:pytest.fail('Unverified operator reached privileged DB'))
    with pytest.raises(SystemExit)as error:
        billing_admin.main(['set-control','--provider','*','--kill-switch','on','--by',str(uuid4()),'--reason','test','--owner-token-stdin'])
    assert error.value.code==2
