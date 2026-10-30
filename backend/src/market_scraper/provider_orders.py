"""Owner-reviewed source accounting into existing canonical invoices and sales.
Original Node invoices.repo/sync.repo rules; existing M95 identity and M98 approval.
No customer PII, stock decrement, credit charge, billing activation or guessed payments.
"""
import hashlib,json
from decimal import Decimal
from uuid import uuid4
from fastapi import HTTPException
from psycopg2.extras import Json
from src.ai.routers.products import _require_catalog_admin
from src.market_scraper.provider_order_values import validate_accounting_projection,timestamp
from src.market_scraper.provider_identity import associate_provider_record
from src.market_scraper.provider_business_staging import decide_provider_business_review


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()


def canonical(conn,tenant,invoice,links):
    with conn.cursor() as c:
        c.execute('SELECT invoice_number,issue_date,subtotal,tax_amount,total_amount,currency,payment_status,customer_name,due_date FROM invoices WHERE tenant_id=%s AND invoice_id=%s FOR UPDATE',(tenant,invoice));header=c.fetchone()
        c.execute('SELECT invoice_item_id,product_id,quantity,unit_price,total_price,rounding_adjustment FROM invoice_items WHERE tenant_id=%s AND invoice_id=%s ORDER BY invoice_item_id FOR UPDATE',(tenant,invoice));items=c.fetchall()
        tids=[x['transaction_id'] for x in links.values() if x.get('transaction_id')]
        c.execute('SELECT transaction_id,product_id,quantity_sold,unit_price,total_price,original_currency,sale_source,transaction_date FROM transactions WHERE tenant_id=%s AND transaction_id=ANY(%s::uuid[]) ORDER BY transaction_id FOR UPDATE',(tenant,tids));sales=c.fetchall()
    return digest({'invoice':header,'items':items,'transactions':sales})


def describe(conn,tenant,source,revision):
    with conn.cursor() as c:
        c.execute('SELECT public.keel_provider_catalog_revision_guard(%s,%s)',(source,revision))
        if not c.fetchone()[0]:raise HTTPException(404,'Active verified source not found.')
        c.execute("SELECT b.provider_record_identity_id,i.provider,i.provider_record_id,b.typed_values,b.validation_findings,b.validation_status,r.decision,i.canonical_invoice_id,i.current_revision_sha256,b.provider_identity_revision_sha256 FROM keel_provider_business_revisions b JOIN keel_provider_record_identities i ON i.tenant_id=b.tenant_id AND i.provider_record_identity_id=b.provider_record_identity_id JOIN ingestion_jobs j ON j.tenant_id=b.tenant_id AND j.job_id=b.ingestion_job_id LEFT JOIN keel_provider_business_reviews r ON r.tenant_id=b.tenant_id AND r.business_revision_id=b.business_revision_id WHERE b.tenant_id=%s AND b.source_id=%s AND b.business_revision_id=%s AND b.entity_type='order' AND j.job_status='COMPLETED' AND NOT EXISTS(SELECT 1 FROM keel_provider_business_revisions n WHERE n.tenant_id=b.tenant_id AND n.provider_record_identity_id=b.provider_record_identity_id AND n.revision_number>b.revision_number)",(tenant,source,revision));row=c.fetchone()
    if not row:raise HTTPException(404,'Latest completed source order not found.')
    identity,provider,external,values,findings,status,review,invoice,current_hash,value_hash=row
    if current_hash!=value_hash:raise HTTPException(409,'Provider order changed. Synchronize and review again.')
    reasons=[];contract=values.get('accounting');resolved={}
    try:
        validate_accounting_projection(contract)
        if contract['externalId']!=external:raise ValueError()
    except (ValueError,TypeError,KeyError):contract=None;reasons.append('accounting_evidence')
    if status=='invalid' or review=='reject' or any(x!={'field':'provider_identity','code':'pending_review'} for x in findings):reasons.append('validation_review')
    with conn.cursor() as c:
        c.execute('SELECT primary_currency,supported_currencies FROM companies WHERE tenant_id=%s',(tenant,));company=c.fetchone()
        c.execute('SELECT business_revision_id,invoice_id,provider_modified_at,canonical_hash,line_links,response FROM keel_provider_order_posts WHERE tenant_id=%s AND provider_record_identity_id=%s ORDER BY created_at DESC,business_revision_id DESC LIMIT 1',(tenant,identity));prior=c.fetchone()
    if contract:
        inv=contract['invoice']
        if inv['currency'] not in [company[0],*(company[1] or [])]:reasons.append('unsupported_currency')
        if prior and timestamp(contract['modifiedAt'])<=timestamp(prior[2].isoformat()) and str(prior[0])!=revision:reasons.append('stale_order')
        for line in inv['items']:
            with conn.cursor() as c:
                c.execute("SELECT i.canonical_product_id,p.currency FROM keel_provider_record_identities i JOIN products p ON p.tenant_id=i.tenant_id AND p.product_id=i.canonical_product_id AND p.deleted_at IS NULL WHERE i.tenant_id=%s AND i.source_id=%s AND i.provider_record_id=%s AND i.entity_type IN ('product','variant') AND i.mapping_status='associated' FOR SHARE OF p",(tenant,source,line['productExternalId']));product=c.fetchone()
            if not product:reasons.append('unlinked_product')
            elif product[1]!=inv['currency']:reasons.append('product_currency')
            else:resolved[line['externalId']]=str(product[0])
    if invoice and (not prior or str(prior[1])!=str(invoice)):reasons.append('unowned_invoice')
    state=canonical(conn,tenant,str(prior[1]),prior[4]) if prior else None
    if prior and state!=prior[3]:reasons.append('canonical_changed')
    number=('SH' if provider=='shopify' else 'WC')+'-'+source+'-'+external.rsplit('/',1)[-1]
    if not prior:
        with conn.cursor() as c:c.execute('SELECT 1 FROM invoices WHERE tenant_id=%s AND lower(invoice_number)=lower(%s)',(tenant,number));collision=c.fetchone()
        if collision:reasons.append('invoice_collision')
    result={'revision':revision,'identity':str(identity),'invoice_number':number,'invoice_id':str(invoice) if invoice else None,'provider':provider,'contract':contract,'resolved_products':resolved,'reasons':sorted(set(reasons)),'eligible':not reasons,'review':review,'prior_revision':str(prior[0]) if prior else None,'canonical_hash':state}
    result['preview_hash']=digest(result)
    return result,prior


def preview(conn,tenant,source,revision):return describe(conn,tenant,source,revision)[0]


def confirm(conn,tenant,actor,source,revision,preview_hash):
    _require_catalog_admin(conn,tenant,actor)
    with conn.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-orders:'+tenant,))
    plan,prior=describe(conn,tenant,source,revision)
    if prior and str(prior[0])==revision:
        if not plan['eligible']:raise HTTPException(409,{'findings':plan['reasons']})
        return {**prior[5],'replayed':True,'canonical_write_performed':False}
    if plan['preview_hash']!=preview_hash:raise HTTPException(409,'Order, products or accounting changed. Review again.')
    if not plan['eligible']:raise HTTPException(409,{'findings':plan['reasons']})
    contract=plan['contract'];inv=contract['invoice'];iid=str(prior[1]) if prior else str(uuid4());old=prior[4] if prior else {};links={}
    if plan['review'] is None:decide_provider_business_review(conn,revision,decision='approve',idempotency_key='orders:'+revision,reason_code='owner_confirmed_order_post')
    with conn.cursor() as c:
        if not prior:c.execute('INSERT INTO invoices(invoice_id,tenant_id,invoice_number,issue_date,subtotal,tax_amount,total_amount,currency,payment_status,created_by_user_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(iid,tenant,plan['invoice_number'],inv['issuedAt'],inv['subtotal'],inv['tax'],inv['total'],inv['currency'],inv['paymentStatus'],actor))
        else:c.execute('UPDATE invoices SET issue_date=%s,subtotal=%s,tax_amount=%s,total_amount=%s,currency=%s,payment_status=%s WHERE tenant_id=%s AND invoice_id=%s',(inv['issuedAt'],inv['subtotal'],inv['tax'],inv['total'],inv['currency'],inv['paymentStatus'],tenant,iid))
        eligible={x['externalId'] for x in contract['lines']}
        for line in inv['items']:
            lid=line['externalId'];link=old.get(lid,{})
            item_id=link.get('invoice_item_id') or str(uuid4());pid=plan['resolved_products'][lid]
            adjustment=Decimal(line['total'])-Decimal(line['unitPrice'])*line['quantity']
            if link:c.execute('UPDATE invoice_items SET product_id=%s,quantity=%s,unit_price=%s,total_price=%s,rounding_adjustment=%s WHERE tenant_id=%s AND invoice_item_id=%s',(pid,line['quantity'],line['unitPrice'],line['total'],adjustment,tenant,item_id))
            else:c.execute('INSERT INTO invoice_items(invoice_item_id,tenant_id,invoice_id,product_id,quantity,unit_price,total_price,rounding_adjustment) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(item_id,tenant,iid,pid,line['quantity'],line['unitPrice'],line['total'],adjustment))
            tid=link.get('transaction_id')
            if lid in eligible:
                new_tid=tid or str(uuid4());sale_source=plan['provider'].upper()
                if tid:c.execute('UPDATE transactions SET product_id=%s,quantity_sold=%s,unit_price=%s,total_price=%s,original_currency=%s,sale_source=%s,transaction_date=%s WHERE tenant_id=%s AND transaction_id=%s',(pid,line['quantity'],line['unitPrice'],line['total'],line['currency'],sale_source,line['date'],tenant,tid))
                else:c.execute('INSERT INTO transactions(transaction_id,tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,sale_source,transaction_date) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(new_tid,tenant,pid,line['quantity'],line['unitPrice'],line['total'],line['currency'],sale_source,line['date']))
                tid=new_tid
            elif tid:c.execute('DELETE FROM transactions WHERE tenant_id=%s AND transaction_id=%s',(tenant,tid));tid=None
            links[lid]={'invoice_item_id':item_id,'transaction_id':tid}
        for lid,link in old.items():
            if lid in links:continue
            if link.get('transaction_id'):c.execute('DELETE FROM transactions WHERE tenant_id=%s AND transaction_id=%s',(tenant,link['transaction_id']))
            c.execute('DELETE FROM invoice_items WHERE tenant_id=%s AND invoice_item_id=%s',(tenant,link['invoice_item_id']))
    if not prior:associate_provider_record(conn,plan['identity'],'invoice',iid,reason_code='owner_confirmed_order_post',evidence_reference=revision)
    result={'invoice_id':iid,'invoice_number':plan['invoice_number'],'invoice_items':len(links),'sales':len(contract['lines']),'payment_status':inv['paymentStatus'],'canonical_write_performed':True,'replayed':False}
    with conn.cursor() as c:
        c.execute('INSERT INTO keel_provider_order_posts(tenant_id,source_id,provider,provider_record_identity_id,business_revision_id,invoice_id,actor_id,provider_modified_at,canonical_hash,line_links,response) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,source,plan['provider'],plan['identity'],revision,iid,actor,contract['modifiedAt'],canonical(conn,tenant,iid,links),Json(links),Json(result)))
        c.execute("INSERT INTO audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(%s,%s,'PROVIDER_ORDER_POSTED','invoices',%s,%s)",(tenant,actor,iid,Json({'source_id':source,'revision':revision,'items':len(links),'sales':len(contract['lines'])})))
    return result
