"""Explicit one-time platform bootstrap using an existing verified Python identity.

Run only through the authorized schema-owner workflow; never exposed over HTTP.
"""
import argparse
import json
from uuid import UUID
from src.ai import db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, type=UUID)
    parser.add_argument('--country', required=True)
    parser.add_argument('--currency', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('--confirm-bootstrap', action='store_true', required=True)
    args = parser.parse_args()
    if len(args.country)!=2 or len(args.currency)!=3 or not args.reason.strip():
        parser.error('Valid country, currency and reason are required')
    conn = db.system_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT keel_bootstrap_platform_owner(%s,%s,%s,%s);',
                (str(args.user_id),args.country.upper(),args.currency.upper(),args.reason))
            tenant_id = str(cursor.fetchone()[0])
        conn.commit()
        print(json.dumps({'platform_tenant_id':tenant_id,'owner_user_id':str(args.user_id)}))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__=='__main__':
    main()
