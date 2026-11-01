"""Synthetic assumptions only; no value here configures production economics."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest
from pydantic import ValidationError
from psycopg2 import errors

from src.ai.billing import plan_analysis, plan_studio
from .test_plan_studio import fixture, assumptions, policy_body, URL
from .test_provider_accounting_db import owner_client, rows  # noqa: F401


def legacy(values):
    values = deepcopy(values)
    values.pop('assumptions_schema_version')
    values.pop('internal_costs_by_plan')
    return dict(values,infrastructure_jod='1',support_jod='1',operations_jod='1')


@pytest.mark.parametrize('value', ['NaN','Infinity','-1',None,'',True,0.1])
def test_internal_amounts_are_exact_finite_nonnegative_and_required(value):
    a = assumptions(); a['internal_costs_by_plan']['starter']['expected']['monthly_jod']=value
    with pytest.raises(ValidationError): plan_studio.TierAssumptions.model_validate(a)


@pytest.mark.parametrize('mutation', ['plan','scenario','amount','unknown','stress','status','date','legacy_fields'])
def test_incomplete_or_ambiguous_policy_never_defaults_or_cross_falls_back(mutation):
    a = assumptions(); tiers = a['internal_costs_by_plan']
    if mutation=='plan': del tiers['growth']
    if mutation=='scenario': del tiers['enterprise']['stress']
    if mutation=='amount': del tiers['starter']['expected']['monthly_jod']
    if mutation=='unknown': tiers['pro']=deepcopy(tiers['enterprise'])
    if mutation=='stress': tiers['starter']['stress']['monthly_jod']='2.99'
    if mutation=='status': tiers['starter']['expected']['status']='verified'
    if mutation=='date': tiers['starter']['expected'].update(measured_from='2026-10-31',measured_to='2026-10-01')
    if mutation=='legacy_fields': a['infrastructure_jod']='3'
    with pytest.raises(ValidationError): plan_studio.TierAssumptions.model_validate(a)


def test_selected_tier_costs_and_approval_are_isolated_and_preserve_decimal_precision():
    p, policy, sources = fixture()
    policy['assumptions']['annual_discount']='0'  # Isolate approval from an independently unsafe annual discount.
    for key,expected,stress in [('starter','3.000001','5.000001'),('growth','8','12'),('enterprise','20','30')]:
        policy['assumptions']['internal_costs_by_plan'][key] = {
            s:dict(monthly_jod=v,status='approved',evidence_ref='SYNTHETIC benchmark',
                   measured_from='2026-10-01',measured_to='2026-10-31',note='Test only')
            for s,v in [('expected',expected),('stress',stress)]}
    for key,expected,stress in [('starter','3.000001','5.000001'),('growth','8','12'),('enterprise','20','30')]:
        p['plan_key']=key
        result = plan_analysis.analyze(p,policy,sources)
        assert result['costs']['internalByScenario']==dict(expected=Decimal(expected),stress=Decimal(stress))
        assert result['costs']['externalByScenario']==dict(expected=Decimal('1.5'),stress=Decimal('3'))
        assert result['costs']['expected']==(Decimal(expected)+Decimal('1.5')).quantize(Decimal('.01'))
        assert result['costs']['stress']==(Decimal(stress)+Decimal('3')).quantize(Decimal('.01'))
        assert result['internalAssumptions']==policy['assumptions']['internal_costs_by_plan'][key]
    policy['assumptions']['internal_costs_by_plan']['growth']['expected']['status']='provisional'
    p['plan_key']='starter'; assert plan_analysis.analyze(p,policy,sources)['status']=='SAFE'
    p['plan_key']='growth'; provisional=plan_analysis.analyze(p,policy,sources)
    assert provisional['status']=='PROVISIONAL' and provisional['pricing'] is not None
    assert 'INTERNAL_ASSUMPTIONS_PROVISIONAL' in provisional['warnings']
    p['plan_key']='basic'; missing=plan_analysis.analyze(p,policy,sources)
    assert missing['status']=='INCOMPLETE_DATA' and missing['pricing'] is None and missing['costs'] is None


def test_internal_scenarios_monthly_three_six_and_annual_preserve_period_allowances():
    p, policy, sources = fixture()
    policy['assumptions']['internal_costs_by_plan']['starter']['stress']['monthly_jod']='5'
    p['prices'].append(dict(amount='100',currency='USD',interval_months=6,period_code='six-months'))
    r = plan_analysis.analyze(p,policy,sources)
    assert r['costs']['expected']==Decimal('4.50') and r['costs']['stress']==Decimal('8.00')
    assert [(x['months'],x['expectedCost'],x['stressCost']) for x in r['periods']]==[
        (1,Decimal('4.50'),Decimal('8.00')),(3,Decimal('10.50'),Decimal('18.00')),
        (6,Decimal('19.50'),Decimal('33.00'))]
    assert r['annual']['expectedCost']==Decimal('54.00') and r['annual']['stressCost']==Decimal('96.00')


def test_explicit_zero_is_valid_but_a_legacy_policy_is_not_current_tier_evidence():
    p,policy,sources=fixture()
    policy['assumptions']['internal_costs_by_plan']['starter']['expected']['monthly_jod']='0'
    plan_studio.TierAssumptions.model_validate(policy['assumptions'])
    assert plan_analysis.analyze(p,policy,sources)['costs']['expected']==Decimal('1.50')
    policy['assumptions']=legacy(policy['assumptions'])
    incomplete=plan_analysis.analyze(p,policy,sources)
    assert incomplete['status']=='INCOMPLETE_DATA' and incomplete['pricing'] is None
    assert incomplete['warnings']==['TIER_INTERNAL_ASSUMPTIONS_MISSING']
    # Reproduce the original characterized v1 result only on explicit replay.
    replay=plan_analysis.analyze(p,policy,sources,replay_legacy=True)
    assert replay['costs']['internal']==Decimal('3') and replay['costs']['expected']==Decimal('4.50')
    assert replay['pricing']['recommended']==Decimal('9.91') and replay['status']=='SAFE'


def test_api_versions_freeze_selected_evidence_and_cannot_mutate_policy(owner_client,owner_db):
    client,_=owner_client; data=client.get(URL).json(); body=policy_body(data)
    body['assumptions']['internal_costs_by_plan']['starter']['expected'].update(
        status='provisional',evidence_ref='SYNTHETIC owner worksheet',note='Not production')
    created=client.post(URL+'/policies',json=body); assert created.status_code==201,created.text
    first=client.post(URL+'/analyze',json={'plan_key':'starter','policy_id':created.json()['policy_id']}).json()
    assert first['status']=='PROVISIONAL' and first['assumptionsSchemaVersion']==2
    assert first['internalAssumptions']['expected']['evidence_ref']=='SYNTHETIC owner worksheet'
    body['assumptions']['internal_costs_by_plan']['starter']['expected']['status']='approved'
    second=client.post(URL+'/policies',json=body); assert second.status_code==201
    approved=client.post(URL+'/analyze',json={'plan_key':'starter','policy_id':second.json()['policy_id']}).json()
    assert approved['status']!='PROVISIONAL'
    saved=next(x for x in client.get(URL+'/history').json()['analyses'] if x['analysis_id']==first['analysisId'])
    assert saved['source_hash']==first['sourceHash'] and saved['snapshot']['status']=='PROVISIONAL'
    assert saved['snapshot']['internalAssumptions']==first['internalAssumptions']
    with pytest.raises(errors.InsufficientPrivilege):
        rows(owner_db,"UPDATE billing_plan_analysis_policies SET assumptions='{}' WHERE policy_id=%s",(created.json()['policy_id'],))
    owner_db.rollback()
    invalid=deepcopy(body);del invalid['assumptions']['internal_costs_by_plan']['enterprise']
    assert client.post(URL+'/policies',json=invalid).status_code==422


def test_legacy_saved_snapshot_and_hash_survive_current_incomplete_analysis(owner_client,owner_db):
    client,_=owner_client; data=client.get(URL).json(); body=policy_body(data)
    body['assumptions']=legacy(body['assumptions'])
    # Simulate an already-existing legacy policy through the original DB
    # command. Current HTTP policy creation must reject this old write shape.
    assert client.post(URL+'/policies',json=body).status_code==422
    from src.ai import db
    from src.ai.core.security import TenantContext
    from src.ai.routers import platform
    app=owner_client[1];ctx=app.dependency_overrides[platform.get_tenant_context]()
    assert isinstance(ctx,TenantContext)
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    try:
        old=plan_studio.command(conn,'create_policy',body);conn.commit()
        p,policy,sources=fixture();policy.update(policy_id=old['policy_id'],assumptions=legacy(assumptions()))
        frozen=plan_analysis.serial(plan_analysis.analyze(p,policy,sources,replay_legacy=True))
        digest=hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        saved=plan_studio.command(conn,'save_analysis',dict(plan_key='starter',mode='analyze',
            policy_id=old['policy_id'],snapshot=frozen,source_hash=digest));conn.commit()
        before=rows(owner_db,'SELECT assumptions FROM billing_plan_analysis_policies WHERE policy_id=%s',(old['policy_id'],))
        current=client.post(URL+'/analyze',json={'plan_key':'starter','policy_id':old['policy_id']})
        assert current.status_code==200 and current.json()['status']=='INCOMPLETE_DATA'
        assert current.json()['pricing'] is None and current.json()['costs'] is None
        assert client.post(URL+'/analyze',json={'plan_key':'starter','policy_id':old['policy_id'],
            'replay_legacy':True}).status_code==422  # Historical replay cannot bypass the HTTP boundary.
        history=client.get(URL+'/history').json()['analyses']
        original=next(x for x in history if x['analysis_id']==saved['analysis_id'])
        assert original['snapshot']==frozen and original['source_hash']==digest
        assert before==rows(owner_db,'SELECT assumptions FROM billing_plan_analysis_policies WHERE policy_id=%s',(old['policy_id'],))
    finally:conn.close()
