"""Sync approved KEEL Standard prices to Paddle Sandbox, using the Stripe operator boundary.

No flags: local plan only, no provider calls. --execute permits provider reads;
--execute --apply additionally permits one durable create per missing object.
Requires a reviewed manifest, original installed binding, isolated TEST installer
DSN, and a current Platform Owner bearer token through stdin. Never web-installed.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg2
from src.ai.billing.paddle_catalog import (CatalogRepository,CatalogAdapter,PaddleCatalogTransport,
    validate_manifest,synchronize,CatalogBlocked)
from src.ai.billing.sandbox_runtime import local_database
from src.ai.billing.paddle_gateway import unique_object


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--execute',action='store_true',help='Separately authorized Paddle Sandbox GET requests')
    parser.add_argument('--apply',action='store_true',help='Separately authorized Product/Price creation and persistent mapping')
    parser.add_argument('--expected-catalog',help='Exact digest from reviewed local plan')
    args=parser.parse_args(argv)
    if args.apply and (not args.execute or not args.expected_catalog):parser.error('Apply requires --execute and --expected-catalog')
    conn=None;transport=None
    try:
        manifest=json.loads(args.manifest.read_text(encoding='utf-8'),object_pairs_hook=unique_object)
        binding=validate_manifest(manifest)
        target=local_database(os.environ)
        if target['dbname']!=manifest['database']:raise CatalogBlocked('Reviewed database mismatch')
        token=sys.stdin.readline().strip()
        if not token:raise CatalogBlocked('Authenticated Platform Owner session required on stdin')
        from src.ai.core.security import get_tenant_context
        ctx=get_tenant_context(authorization='Bearer '+token)
        conn=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=3)
        repo=CatalogRepository(conn,ctx.user_id,ctx.tenant_id,manifest)
        rows,expected=repo.snapshot()
        if args.expected_catalog and expected!=args.expected_catalog:raise CatalogBlocked('Catalog changed since approval')
        if not args.execute:
            print(json.dumps(dict(mode='LOCAL PLAN ONLY; no provider calls',catalog_digest=expected,prices=len(rows),products=len({r['plan_key'] for r in rows}))))
            return 0
        key=os.environ.get('KEEL_SANDBOX_PADDLE_API_KEY','')
        transport=PaddleCatalogTransport(binding,key)
        result=synchronize(repo,CatalogAdapter(binding,transport),expected=expected,apply=args.apply)
        print(json.dumps(result));return 0
    except Exception:
        # Neither provider diagnostics nor credentials/tokens are emitted.
        print('BLOCKED: current owner, isolated binding, catalog approval, provider discovery or recovery requires review.',file=sys.stderr)
        return 2
    finally:
        if transport is not None:transport._client.close()
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
