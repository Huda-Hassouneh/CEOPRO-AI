"""Bounded Phase 1A tests. Native tests require the existing disposable billing DB guard."""
import argparse
import os
import subprocess
import sys
import tempfile
from scripts.billing_verification import BACKEND, validate_test_environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',action='store_true')
    parser.add_argument('--junitxml')
    args=parser.parse_args()
    url=validate_test_environment(dict(os.environ),database=args.database)
    env=dict(os.environ)
    env.update(BILLING_DATABASE_TESTS='1'if args.database else'0',PYTHONDONTWRITEBYTECODE='1',
               KEEL_TEST_DISABLE_METERING='0',UNASSIGNED_PLAN_ACCESS='none',
               JWT_SECRET='phase1a-isolated-test-secret-not-for-deployment')
    if args.database:
        if env.get('PHASE1A_ISOLATED_DATABASE') != 'YES':
            parser.error('Explicit dedicated disposable database acknowledgment required')
        if env.get('BILLING_TEST_ENGINE'):
            parser.error('Native PostgreSQL 17 required; no alternate engine is accepted')
        env['DATABASE_URL']=url;env['AI_TEST_DATABASE_URL']=url
    else:
        for key in ['DATABASE_URL','AI_TEST_DATABASE_URL','BILLING_TEST_DATABASE_URL','APP_DB_PASSWORD']:
            env.pop(key,None)
    command=[sys.executable,'-m','pytest','-q','-ra','tests/keel_integration']
    if args.junitxml:command+=['--junitxml',args.junitxml]
    with tempfile.TemporaryDirectory(prefix='keel-phase1a-tests-')as cache:
        command+=['-o','cache_dir='+cache]
        return subprocess.call(command,cwd=BACKEND,env=env)


if __name__=='__main__':raise SystemExit(main())
