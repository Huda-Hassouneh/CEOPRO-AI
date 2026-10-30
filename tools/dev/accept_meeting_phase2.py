"""Bounded acceptance against the designated local synthetic meeting tenant.

Never seeds, changes plans, or applies a recommended price. Private evidence only.
"""
import csv
import io
import json
from contextlib import closing
from decimal import Decimal
from datetime import datetime, timezone
import sys
import uuid

import dev
import database
from seed_meeting_demo import login, fingerprints, read, BASE


def main():
    c = dev.config()
    if str(dev.PYTHON.resolve()).lower() != str(__import__('pathlib').Path(sys.executable).resolve()).lower():
        import subprocess
        return subprocess.call([str(dev.PYTHON), __file__])
    evidence = dev.STATE / 'evidence' / 'meeting-phase2'
    evidence.mkdir(parents=True, exist_ok=True)
    if (evidence / 'run.json').exists() or (evidence / 'before.json').exists():
        raise RuntimeError('Acceptance already started; preserve evidence and inspect before any paid replay.')
    client, account = login(c)
    tenant = account['tenant_id']
    results = []

    def save(name, value):
        dev.write_json(evidence / (name + '.json'), value)

    def check(name, ok, detail=''):
        row = dict(name=name, status='PASS' if ok else 'FAIL', detail=detail)
        results.append(row)
        print(row['status'] + ': ' + name, flush=True)
        save('checks', results)

    def request(method, path, **kwargs):
        r = client.http.request(method, path, headers={**client.headers, **kwargs.pop('headers', {})}, **kwargs)
        return r

    # Read-only repeatable snapshot: all non-demo tenant records and all billing
    # records; original seeded rows are scoped by immutable product IDs.
    def snapshot():
        from psycopg2 import sql
        with closing(database.connect(c, external=False)) as conn:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor() as cur:
                cur.execute('SELECT tenant_id::text FROM companies WHERE tenant_id<>%s', (tenant,))
                others = [x[0] for x in cur.fetchall()]
                other = fingerprints(conn, tenants=others)
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND (table_name LIKE 'billing_%%' OR table_name IN ('tenant_plan_assignments','provider_cost_schedules'))")
                billing = fingerprints(conn, tables=[x[0] for x in cur.fetchall()])
                business = {}
                for table in ('products','inventory','invoices','invoice_items','transactions','tenant_competitors','competitor_prices'):
                    where = "tenant_id=%s"
                    if table == 'products':
                        where += " AND sku LIKE 'DEMO-%'"
                    if table == 'inventory':
                        where += " AND product_id IN (SELECT product_id FROM products WHERE tenant_id=%s AND sku LIKE 'DEMO-%%')"
                    args = (tenant, tenant) if table == 'inventory' else (tenant,)
                    cur.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM (SELECT md5(row_to_json(t)::text) h FROM {} t WHERE " + where.replace("LIKE 'DEMO-%'", "LIKE 'DEMO-%%'") + ") s").format(sql.Identifier(table)), args)
                    business[table] = list(cur.fetchone())
                cur.execute('SELECT * FROM tenant_credit_balances WHERE tenant_id=%s', (tenant,))
                credits = [dict(zip([d.name for d in cur.description], row)) for row in cur.fetchall()]
                return dict(other_tenants=other, billing=billing, business=business, credits=json.loads(json.dumps(credits, default=str)))

    before = snapshot()
    save('before', before)
    catalog = client.request('GET', '/catalog/products', params={'pageSize':100})
    products = catalog['products']
    pid = next(p['id'] for p in products if p.get('sku') == 'DEMO-001')
    check('ten active original products', catalog['pagination']['total'] == 10)
    for name, path, params in (
        ('forecast','/forecasting/overview',{'auto_refresh':'false'}),
        ('alerts','/alerts',{}), ('imports','/extraction/imports',{}),
        ('connections','/onboarding/sources',{}), ('competitors','/competitors',{}),
        ('financial','/reports/financial-summary',{'window_days':365}),
        ('billing','/billing/subscription',{}), ('documents','/rag/documents',{}),
        ('sessions','/rag/sessions',{}), ('marketing-options','/marketing/options',{})):
        r = request('GET', path, params=params)
        save(name, r.json())
        check(name+' read', r.status_code == 200, str(r.status_code))
    check('tenant owner denied platform administration', request('GET','/platform/me').status_code == 403)
    check('unauthenticated catalog denied', client.http.get('/catalog/products').status_code == 401)

    # Disposable manual product, zero sales. Cleanup is attempted even on failure.
    disposable = None
    try:
        r = request('POST','/products',json={'product_name':{'en':'Phase 2 Disposable','ar':'اختبار مؤقت'},'sku':'PHASE2-'+uuid.uuid4().hex[:10], 'current_price':2.5,'cost_price':1.25,'currency':'JOD','initial_stock_quantity':2})
        save('product-create',r.json())
        check('disposable product created', r.status_code == 200)
        if r.status_code == 200:
            disposable = r.json()['product_id']
            r = request('PATCH',f'/products/{disposable}',json={'current_price':3.25})
            check('disposable price update persisted',r.status_code == 200 and request('GET',f'/products/{disposable}').json()['current_price'] == 3.25)
            r = request('PATCH',f'/products/{disposable}/inventory',json={'stock_quantity':'4.5','reorder_level':2,'safety_stock':1})
            check('fractional inventory persisted',r.status_code == 200 and Decimal(str(request('GET',f'/products/{disposable}').json()['inventory']['stock_quantity'])) == Decimal('4.5'))
            check('negative inventory rejected',request('PATCH',f'/products/{disposable}/inventory',json={'stock_quantity':-1}).status_code == 422)
    finally:
        if disposable:
            check('disposable product deleted',request('DELETE',f'/products/{disposable}').status_code == 200)
            check('deleted product inaccessible',request('GET',f'/products/{disposable}').status_code == 404)

    for fmt in ('json','csv'):
        key = 'meeting-phase2-export-'+fmt
        r = request('GET','/reports/sales/export',params={'format':fmt},headers={'Idempotency-Key':key})
        (evidence / ('sales.'+fmt)).write_bytes(r.content)
        check(fmt+' export download',r.status_code == 200 and 'attachment' in r.headers.get('content-disposition',''))
        if r.status_code == 200:
            rows = r.json()['rows'] if fmt == 'json' else list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
            save(fmt+'-columns',list(rows[0]) if rows else [])
            if fmt == 'json':
                check('JSON all 1800 lines and exact revenue',len(rows)==1800 and sum(Decimal(str(x['total_price'])) for x in rows)==Decimal('85892.200'))
            else:
                check('CSV all 1800 lines',len(rows)==1800)
            retry = request('GET','/reports/sales/export',params={'format':fmt},headers={'Idempotency-Key':key})
            check(fmt+' export retry succeeds',retry.status_code==200)

    r = request('POST','/pricing/recommend',params={'product_id':pid},headers={'Idempotency-Key':'meeting-phase2-pricing-v1'})
    save('pricing-recommend',r.json())
    check('real pricing decision',r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        retry = request('POST','/pricing/recommend',params={'product_id':pid},headers={'Idempotency-Key':'meeting-phase2-pricing-v1'})
        check('pricing idempotent replay',retry.json()==r.json())
    save('pricing-history',request('GET',f'/pricing/history/{pid}').json())

    payload = read(BASE / 'marketing-request.json')
    payload['request_key'] = 'meeting-phase2-marketing-v1'
    r = request('POST','/marketing/campaigns',json=payload)
    save('marketing-create',r.json())
    check('real marketing copy generation',r.status_code==200 and r.json().get('status')=='COMPLETED',str(r.status_code))
    campaign = r.json().get('campaign_id') if r.status_code==200 else None
    if campaign:
        save('marketing-reload',request('GET',f'/marketing/campaigns/{campaign}').json())
        image = request('POST',f'/marketing/campaigns/{campaign}/generate-image',json={})
        save('marketing-image',image.json())
        check('real marketing image generation',image.status_code==200 and image.json().get('image_generation_status')=='COMPLETED',str(image.status_code))

    # Additional structured-business RAG path, beyond the prior document questions.
    r = request('POST','/rag/query',params={'query_text':'Which product has the highest total revenue across all our sales history? Give its revenue and explain your calculation.'})
    save('rag-business',r.json())
    check('RAG business question answered',r.status_code==200,str(r.status_code))
    if r.status_code==200 and r.json().get('session_id'):
        save('rag-history',request('GET',f"/rag/sessions/{r.json()['session_id']}/messages").json())
    after = snapshot()
    save('after',after)
    for section in ('other_tenants','billing','business'):
        check(section+' preserved since Phase 2 start',before[section]==after[section])
    save('run',dict(commit=dev.run(['git','rev-parse','HEAD'],capture=True).strip(),finished_at=datetime.now(timezone.utc).isoformat(),response_mocks=False,tenant=tenant))


if __name__ == '__main__':
    main()
