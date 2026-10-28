"""Read-only acceptance reconciliation; no generation, seed, or billing writes."""
import csv
import io
import json
import os
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP

import dev
import database
from seed_meeting_demo import login, read, fingerprints


def main():
    c = dev.config()
    e = dev.STATE / 'evidence' / 'meeting-phase2'
    client, a = login(c)
    checks = []
    def check(name, ok, detail=None):
        checks.append(dict(name=name,status='PASS' if ok else 'FAIL',detail=detail))
        print(checks[-1]['status']+': '+name,flush=True)
    rows = read(e/'sales.json')['rows']
    csv_rows = list(csv.DictReader(io.StringIO((e/'sales.csv').read_text(encoding='utf-8-sig'))))
    for label, dataset, total, profit in [('JSON',rows,'total_price','line_gross_profit'),('CSV',csv_rows,'Total','Gross Profit')]:
        check(label+' exact revenue and gross profit',sum(Decimal(str(x[total])) for x in dataset)==Decimal('85892.200') and sum(Decimal(str(x[profit])) for x in dataset)==Decimal('33257.500'))
    if (e/'browser-sales.csv').exists():
        browser = list(csv.DictReader(io.StringIO((e/'browser-sales.csv').read_text(encoding='utf-8-sig'))))
        check('browser CSV exact full history',len(browser)==1800 and sum(Decimal(x['Total']) for x in browser)==Decimal('85892.200'))
    for name,path,params in [('market-structure','/discovery/market/structure',{}),('market-analysis','/discovery/market/analysis',{}),('reviews','/reviews',{}),('sentiment','/sentiment/summary',{'subject_type':'BUSINESS'})]:
        r=client.http.get(path,params=params,headers=client.headers)
        dev.write_json(e/(name+'.json'),r.json())
        check(name+' response',r.status_code==200,str(r.status_code))
    image=read(e/'marketing-image.json')
    cid=image['campaign_id']
    r=client.http.get(f'/marketing/campaigns/{cid}/image',headers=client.headers)
    check('authenticated generated image retrieved',r.status_code==200 and r.headers.get('content-type','').startswith('image/'))
    if r.status_code==200:
        (e/'marketing-generated.webp').write_bytes(r.content)
        from PIL import Image
        im=Image.open(io.BytesIO(r.content))
        check('generated image decoded',im.size==(768,768),str(im.size))
    payload=read(e/'marketing-create.json')
    reload=client.request('GET',f'/marketing/campaigns/{cid}')
    check('marketing copy persisted exactly',reload['content']==payload['content'])
    # Verify RAG content against required full-history business facts, not HTTP.
    rag=read(e/'rag-business.json')
    text=json.dumps(rag.get('answer_blocks'),ensure_ascii=False)
    check('RAG obeys all-history revenue scope','33,132' in text or '33132' in text,'Expected 4L oil JOD 33,132; response uses last 90 days JOD 18,315.')
    if rag.get('session_id'):
        history=client.request('GET',f"/rag/sessions/{rag['session_id']}/messages")
        dev.write_json(e/'rag-history-final.json',history)
    with closing(database.connect(c,external=False)) as conn,conn.cursor() as cur:
        baseline=read(e/'before.json')
        from psycopg2 import sql
        for table,clause in [('products',"sku LIKE 'DEMO-%%'"),('inventory',"product_id IN (SELECT product_id FROM products WHERE tenant_id=%s AND sku LIKE 'DEMO-%%')")]:
            args=(a['tenant_id'],a['tenant_id']) if table=='inventory' else (a['tenant_id'],)
            cur.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM (SELECT md5(row_to_json(t)::text) h FROM {} t WHERE tenant_id=%s AND "+clause+") s").format(sql.Identifier(table)),args)
            check('original '+table+' rows unchanged',list(cur.fetchone())==baseline['business'][table])
        current=fingerprints(conn,tenants=[a['tenant_id']],tables=['invoices','invoice_items','transactions','competitor_prices'])
        check('original invoices sales and competitor price facts unchanged',all(current[name]==baseline['business'][name] for name in current))
        billing=fingerprints(conn,tables=list(baseline['billing']))
        check('all baseline billing tables unchanged',billing==baseline['billing'])
        cur.execute("SELECT count(*),bool_and(replayed) FROM metered_request_keys WHERE tenant_id=%s AND feature_code='monthly_reports' AND idempotency_key LIKE '%%meeting-phase2-export-%%'",(a['tenant_id'],))
        count,replayed=cur.fetchone()
        check('two API export identities counted once with replay',count==2 and replayed)
        cur.execute('SELECT status,consumed_credits,actual_cost_usd,provider,provider_operation,idempotency_key FROM usage_ledger WHERE tenant_id=%s ORDER BY created_at',(a['tenant_id'],))
        ledger=cur.fetchall()
        cur.execute("SELECT reserved_credits,consumed_credits,consumed_cost_usd FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind='ai'",(a['tenant_id'],))
        reserved,consumed,cost=cur.fetchone()
        check('zero outstanding AI reservations',reserved==0 and all(x[0]!='reserved' for x in ledger))
        check('AI balance equals settled ledger',consumed==sum((x[1] or Decimal(0) for x in ledger),Decimal(0)) and cost==sum(((x[2] or Decimal(0)).quantize(Decimal('.000001'),rounding=ROUND_HALF_UP) for x in ledger),Decimal(0)))
        check('provider ledger identities unique',len(ledger)==len({x[5] for x in ledger}))
        dev.write_json(e/'accounting.json',{'reserved':str(reserved),'consumed_ai_credits':str(consumed),'metered_cost_usd':str(cost),'ledger_entries':len(ledger),'providers':sorted({str(x[3]) for x in ledger})})
        cur.execute('SELECT sku,current_price,cost_price FROM products WHERE tenant_id=%s AND deleted_at IS NULL ORDER BY sku',(a['tenant_id'],))
        check('only ten original active SKUs remain',[x[0] for x in cur.fetchall()]==[f'DEMO-{i:03}' for i in range(1,11)])
        cur.execute('SELECT global_competitor_id,competition_level,product_match_rate,classification_reason FROM tenant_competitors WHERE tenant_id=%s ORDER BY global_competitor_id',(a['tenant_id'],))
        dev.write_json(e/'competitor-derived-fields.json',json.loads(json.dumps(cur.fetchall(),default=str)))
    previous=os.environ.copy()
    try:
        os.environ.update(dev.environment(c,external=False))
        from src.ai import db
        for context,label in [(a['tenant_id'],'own'),('00000000-0000-0000-0000-000000000000','unrelated')]:
            with closing(db.app_role_connection(context,a['user_id'] if label=='own' else context)) as conn,conn.cursor() as cur:
                cur.execute('SELECT current_user')
                check(label+' restricted role',cur.fetchone()[0]=='ceopro_app')
                if label=='own':
                    cur.execute('SELECT count(*) FROM products WHERE tenant_id<>%s',(a['tenant_id'],))
                    check('RLS hides foreign products',cur.fetchone()[0]==0)
                else:
                    cur.execute('SELECT count(*) FROM invoices WHERE tenant_id=%s',(a['tenant_id'],))
                    check('RLS hides populated demo invoices',cur.fetchone()[0]==0)
    finally:
        os.environ.clear();os.environ.update(previous)
    dev.write_json(e/'reconciliation.json',checks)


if __name__=='__main__':
    main()
