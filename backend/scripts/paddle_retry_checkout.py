"""Operator-only definitive Paddle TEST rejection review; never submits Checkout.

Use an authenticated Platform Owner token on stdin, explicit isolated installer
DATABASE_URL, reviewed acceptance manifest and the original private server log.
Only the known HTTP 400 domain-validation error is admitted. Fresh bound GETs
occur before the DB transaction. Ambiguity, drift and nonempty recovery block.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,os,sys
from pathlib import Path
import httpx,psycopg2
from psycopg2.extras import Json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.ai.billing.sandbox_runtime import local_database
from src.ai.billing.paddle_gateway import unique_object


def rejection_evidence(record,dispatch):
    response=record.get('response') or {};error=response.get('error') or {}
    if (record.get('method')!='POST' or record.get('path')!='/transactions'
            or record.get('status')!=400 or record.get('exception_type')
            or error.get('type')!='request_error'
            or error.get('code')!='transaction_checkout_url_domain_is_not_approved'
            or response.get('data') is not None or not response.get('meta',{}).get('request_id')
            or record.get('request')!=dispatch['request']['transport']):
        raise ValueError('Not a conclusive original domain-validation rejection')
    return dict(status=400,error=error,request_id=response['meta']['request_id'],
        response_sha256='sha256:'+hashlib.sha256(json.dumps(response,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),
        response=response)


def discover(client,manifest,dispatch):
    account=client.get('/account');account.raise_for_status();account=account.json()['data']
    if account['id']!=manifest['merchant_account_id']:raise ValueError('Original namespace required')
    response=client.get('/transactions',params={'customer_id':dispatch['provider_customer_id'],'per_page':100})
    response.raise_for_status();body=response.json()
    # An empty, complete Customer-scoped response is required, not a partial
    # metadata match or an inference from current provider configuration.
    if body['data']!=[] or body['meta']['pagination']['has_more'] is not False:
        raise ValueError('Complete empty original Customer recovery required')
    return dict(namespace=account,recovery=dict(status=200,data=[],has_more=False,
        customer_id=dispatch['provider_customer_id'],request_id=body['meta']['request_id'],
        observed_at=datetime.now(timezone.utc).isoformat(),response=body))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--rejection-log',type=Path,required=True)
    p.add_argument('--authorization-reference',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv);conn=None
    try:
        manifest=json.loads(args.manifest.read_text(encoding='utf-8'),object_pairs_hook=unique_object)
        if manifest['provider']!='paddle' or manifest['environment']!='test':raise ValueError('TEST only')
        target=local_database(os.environ)
        if target['dbname']!=manifest['database']:raise ValueError('Exact isolated database required')
        from src.ai.core.security import get_tenant_context
        ctx=get_tenant_context(authorization='Bearer '+sys.stdin.readline().strip())
        conn=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=3)
        with conn.cursor() as q:
            q.execute("SELECT 1 FROM keel_platform_members m CROSS JOIN keel_platform_workspace w WHERE m.user_id=%s AND m.role_key='owner' AND m.status='active' AND w.tenant_id=%s AND keel_active_principal(m.user_id,w.tenant_id)",(ctx.user_id,ctx.tenant_id))
            if q.fetchone() is None:raise ValueError('Current authenticated Platform Owner required')
            q.execute('SELECT to_jsonb(d) FROM billing_journey_dispatches d WHERE attempt_id=%s',(manifest['operation_id'],))
            row=q.fetchone()
        conn.commit()
        if row is None:raise ValueError('Original dispatch required')
        dispatch=row[0]
        if (dispatch['tenant_id']!=manifest['tenant_id'] or dispatch['binding_id']!=manifest['binding_id']
                or dispatch['provider_checkout_id'] is not None):raise ValueError('Original unresolved dispatch required')
        records=[json.loads(line,object_pairs_hook=unique_object) for line in args.rejection_log.read_text(encoding='utf-8').splitlines()]
        posts=[r for r in records if r.get('method')=='POST' and r.get('path')=='/transactions']
        if len(posts)!=1:raise ValueError('Exactly one recorded original submission required')
        rejection=rejection_evidence(posts[0],dispatch)
        key=os.environ.get('KEEL_SANDBOX_PADDLE_API_KEY','')
        if not key.startswith('pdl_sdbx_apikey_'):raise ValueError('Sandbox credential required')
        with httpx.Client(base_url='https://sandbox-api.paddle.com',trust_env=False,follow_redirects=False,timeout=10,
                headers={'Authorization':'Bearer '+key,'Paddle-Version':'1'}) as client:
            evidence=discover(client,manifest,dispatch)
        evidence.update(binding_id=dispatch['binding_id'],merchant_account_id=manifest['merchant_account_id'],
            customer_id=dispatch['provider_customer_id'],request=dispatch['request']['transport'],rejection=rejection,
            original_log_sha256='sha256:'+hashlib.sha256(args.rejection_log.read_bytes()).hexdigest())
        with conn.cursor() as q:
            q.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",(ctx.tenant_id,ctx.user_id))
            q.execute('SELECT billing_authorize_checkout_retry(%s,%s,%s)',(manifest['operation_id'],Json(evidence),args.authorization_reference))
            authorization=q.fetchone()[0]
        conn.commit()
        # This receipt records authorization, not a completed send. The existing
        # restricted dispatch elect consumes it once under original row locks.
        args.output.write_text(json.dumps(authorization,indent=2),encoding='utf-8')
        print(json.dumps(dict(retry_id=authorization['retry_id'],attempt_id=authorization['attempt_id'],authorized=True,provider_posts=0)))
        return 0
    except Exception:
        if conn:conn.rollback()
        print('BLOCKED: original definitive rejection, current owner, scoped recovery or retry authorization failed.',file=sys.stderr)
        return 2
    finally:
        if conn:conn.close()


if __name__=='__main__':raise SystemExit(main())
