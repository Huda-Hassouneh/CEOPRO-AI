"""Synthetic owner fixture restricted to the repository's disposable test namespace."""
import json
import os
from dataclasses import replace
from pathlib import Path
from scripts.billing_verification import validate_test_environment
from scripts.ci_smoke_account import _verify_synthetic_account,_complete_guided_onboarding
from scripts.demo_companies.seed import Client,configure_company
from scripts.demo_companies.profiles import COMPANIES
from src.ai import db

def main():
    validate_test_environment(dict(os.environ),database=True)
    password=os.environ['E2E_PASSWORD'];api=os.environ['E2E_API'];rows={}
    for role in ('owner','customer'):
        email=f'original-billing-{role}@example.test';company=replace(COMPANIES[0],business_name='SYNTHETIC Billing '+role,products=COMPANIES[0].products[:1])
        client=Client(api);account=_verify_synthetic_account(client,company,email,password)
        configure_company(client,company);_complete_guided_onboarding(client,company)
        conn=db.system_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT user_id FROM users WHERE email=%s',(email,));uid=str(cur.fetchone()[0])
                if role=='owner':cur.execute("SELECT keel_bootstrap_platform_owner(%s,'US','USD','SYNTHETIC DISPOSABLE BROWSER FIXTURE')",(uid,))
            conn.commit()
        finally:conn.close()
        rows[role]={'email':email,'user_id':uid,'tenant_id':account['tenant_id']}
    Path(os.environ['E2E_FIXTURE_FILE']).write_text(json.dumps(rows,indent=2))
    print('Prepared two verified synthetic identities; one isolated Platform Owner; no Stripe objects.')
if __name__=='__main__':main()
