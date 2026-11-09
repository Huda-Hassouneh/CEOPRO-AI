"""Approval-gated local-app sandbox acceptance driver; never direct provider API.

Default: print the procedure, perform no requests. --execute requires an explicit
reviewed manifest and an initiating billing user's TEST session. This tool cannot
install policies, collect consent, provision SQL services or enable feature flags.
"""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID


def validate_manifest(value):
    if type(value) is not dict:raise ValueError('Reviewed manifest required')
    u=urlsplit(value['base_url'])
    if (u.scheme!='http' or u.hostname not in ('127.0.0.1','localhost','::1') or not u.port
            or u.username or u.password or u.path not in ('','/') or u.query or u.fragment):
        raise ValueError('Explicit loopback local application required')
    if value.get('environment')!='test' or value.get('provider') not in ('stripe','paddle') or value.get('synthetic_business') is not True:
        raise ValueError('Explicit synthetic sandbox business required')
    UUID(value['operation_id'])
    for key in ('binding_id','provider_operations_authorization','merchant_approval_reference','legal_approval_reference'):
        if type(value.get(key)) is not str or not value[key].strip():raise ValueError('Missing approval or binding reference')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',value.get('policy_bundle_digest','')):raise ValueError('Approved policy bundle digest required')
    return value


def _scope(value,manifest,*,policy=False):
    if (value.get('provider')!=manifest['provider'] or value.get('environment')!=manifest['environment']
            or value.get('binding_id')!=manifest['binding_id'] or value.get('operation_id')!=manifest['operation_id']
            or policy and value.get('policy_bundle_digest')!=manifest['policy_bundle_digest']):
        raise ValueError('Original sandbox operation/binding required')


def run(value,action,client):
    """Client is loopback-only, authenticated and redirect-disabled in main."""
    if action not in ('status','advance','checkout','cancellation','cleanup'):raise ValueError('Unsupported acceptance action')
    v=validate_manifest(value);path='/billing/trial-journeys/'+v['operation_id']
    if action in ('advance','checkout'):
        reply=client.get(path+'/checkout',params={'language':v.get('language','en')});reply.raise_for_status();scope=reply.json()
        _scope(scope,v,policy=True)
        if action=='checkout':return {'state':'checkout_bound' if scope.get('transaction_id') else 'not_dispatched'}
    else:
        # Existing progress rechecks the initiating actor and current billing
        # authority through protected reads, independently of consent validity.
        # Cleanup must remain usable after withdrawal or policy supersession.
        reply=client.get(path+'/progress');reply.raise_for_status()
        _scope(reply.json(),v)
    if action!='status':
        reply=client.post(path+'/'+action,json={'language':v.get('language','en')} if action=='advance' else {})
    reply.raise_for_status();data=reply.json()
    # No raw provider bodies, tokens, personal data or signed Checkout URLs.
    return {key:data[key] for key in ('state','reason') if key in data}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--action',choices=('status','advance','checkout','cancellation','cleanup'),default='status')
    parser.add_argument('--execute',action='store_true',help='Separately authorized sandbox provider operations via local application')
    args=parser.parse_args()
    if not args.execute:
        print('PLAN ONLY: no requests. Install reviewed policies/merchant capabilities and isolated TEST service composition; register a synthetic B2B business, verify account, reserve original plan, explicitly accept approved consent in UI. Then supply reviewed manifest and local session. Advance once; recover same operation after timeout; complete provider-hosted sandbox Checkout manually; deliver genuine signed notifications; verify B4, paid renewal, failure/recovery, cancellation and exact entitlement cutoff. See RECURRING_CONSENT_FOUNDATION.md.')
        return
    if args.manifest is None:parser.error('Reviewed authorization manifest required')
    try:
        value=validate_manifest(json.loads(args.manifest.read_text(encoding='utf-8')))
        token=os.environ.get('KEEL_SANDBOX_ACCESS_TOKEN')
        if not token:raise ValueError('Authenticated initiating TEST session required')
        import httpx
        with httpx.Client(base_url=value['base_url'].rstrip('/'),headers={'Authorization':'Bearer '+token},
                          trust_env=False,follow_redirects=False,timeout=10) as client:
            result=run(value,args.action,client)
    except Exception:
        print('BLOCKED: approval, scope, consent, provider capability or local application refused. Inspect private server evidence; do not retry with a new operation.')
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__=='__main__':main()
