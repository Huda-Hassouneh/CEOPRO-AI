"""Network-free definitive rejection classification; no provider acceptance."""
from copy import deepcopy
from datetime import datetime,timezone
import httpx,pytest
from scripts.paddle_retry_checkout import rejection_evidence,discover


def original():
    body={'customer_id':'ctm_original','items':[{'price_id':'pri_original','quantity':1}]}
    return dict(method='POST',path='/transactions',status=400,request=body,response=dict(
        error=dict(type='request_error',code='transaction_checkout_url_domain_is_not_approved'),meta=dict(request_id='original_request'))),dict(request=dict(transport=body))


@pytest.mark.parametrize('problem',['valid','timeout','5xx','429','unknown_code','wrong_request','missing_receipt','not_original_post'])
def test_only_complete_original_domain_rejection_is_admitted(problem):
    record,dispatch=original()
    if problem=='timeout':record['exception_type']='TimeoutError'
    if problem=='5xx':record['status']=503
    if problem=='429':record['status']=429
    if problem=='unknown_code':record['response']['error']['code']='unknown'
    if problem=='wrong_request':record=deepcopy(record);record['request']['customer_id']='other'
    if problem=='missing_receipt':record['response']['meta']={}
    if problem=='not_original_post':record['path']='/customers'
    if problem=='valid':assert rejection_evidence(record,dispatch)['status']==400
    else:
        with pytest.raises(ValueError):rejection_evidence(record,dispatch)


@pytest.mark.parametrize('problem',['valid','nonempty','partial','merchant','unavailable'])
def test_recovery_requires_fresh_complete_bound_empty_response(problem):
    calls=[]
    def answer(request):
        calls.append(request)
        if request.url.path=='/account':return httpx.Response(200,json=dict(data=dict(id='other' if problem=='merchant' else 'merchant')))
        assert request.method=='GET' and request.url.params['customer_id']=='ctm_original'
        return httpx.Response(503 if problem=='unavailable' else 200,json=dict(data=[{'id':'txn_exists'}] if problem=='nonempty' else [],
            meta=dict(request_id='recovery',pagination=dict(has_more=problem=='partial'))))
    with httpx.Client(base_url='https://sandbox-api.paddle.com',transport=httpx.MockTransport(answer)) as client:
        if problem=='valid':
            evidence=discover(client,dict(merchant_account_id='merchant'),dict(provider_customer_id='ctm_original'))
            assert evidence['recovery']['data']==[] and datetime.fromisoformat(evidence['recovery']['observed_at']).tzinfo
        else:
            with pytest.raises((ValueError,httpx.HTTPStatusError)):discover(client,dict(merchant_account_id='merchant'),dict(provider_customer_id='ctm_original'))
    assert all(r.method=='GET' for r in calls)
