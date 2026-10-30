"""Explicit single-balance stock reconciliation through existing M96 authority.
No summing different quantity fields/locations or silent manual/source precedence.
All physical source observations remain available as independent evidence.
"""
from decimal import Decimal
from fastapi import HTTPException
from src.ai.routers import products
from src.market_scraper.provider_orders import digest
from src.market_scraper.inventory_provenance import register_canonical_inventory_location,decide_provider_location_association,decide_inventory_authority


def describe(conn,tenant,source,observation):
    with conn.cursor() as c:
        c.execute('SELECT public.keel_provider_catalog_source_guard(%s)',(source,))
        if not c.fetchone()[0]:raise HTTPException(404,'Active verified source not found.')
        c.execute("SELECT o.provider,o.provider_record_identity_id,o.provider_location_identity_id,o.quantity_semantics,o.quantity,i.canonical_product_id,pl.provider_location_id,(SELECT business_revision_id FROM keel_provider_business_revisions b WHERE b.tenant_id=i.tenant_id AND b.provider_record_identity_id=i.provider_record_identity_id ORDER BY revision_number DESC LIMIT 1) FROM keel_inventory_observations o JOIN keel_provider_record_identities i ON i.tenant_id=o.tenant_id AND i.provider_record_identity_id=o.provider_record_identity_id LEFT JOIN keel_provider_inventory_locations pl ON pl.tenant_id=o.tenant_id AND pl.provider_location_identity_id=o.provider_location_identity_id WHERE o.tenant_id=%s AND o.source_id=%s AND o.inventory_observation_id=%s AND EXISTS(SELECT 1 FROM keel_provider_stock_scan_members m JOIN ingestion_jobs j ON j.tenant_id=m.tenant_id AND j.job_id=m.ingestion_job_id WHERE m.tenant_id=o.tenant_id AND m.source_id=o.source_id AND m.inventory_observation_id=o.inventory_observation_id AND j.job_status='COMPLETED' AND j.job_id=(SELECT n.job_id FROM ingestion_jobs n WHERE n.tenant_id=o.tenant_id AND n.source_id=o.source_id AND n.job_status='COMPLETED' ORDER BY n.created_at DESC,n.job_id DESC LIMIT 1))",(tenant,source,observation));row=c.fetchone()
    if not row:raise HTTPException(404,'Observation is not part of the latest completed scan. Unknown or missing stock is never zero.')
    provider,identity,location,semantics,quantity,pid,provider_location,revision=row;reasons=[];stock=[];prior=None;authority=None
    if not pid:reasons.append('unlinked_product')
    elif not revision:reasons.append('validation_review')
    else:
        with conn.cursor() as c:
            c.execute('SELECT public.keel_provider_catalog_revision_guard(%s,%s)',(source,revision));c.fetchone()
            c.execute('SELECT product_id FROM products WHERE tenant_id=%s AND product_id=%s AND deleted_at IS NULL FOR UPDATE',(tenant,pid))
            if not c.fetchone():reasons.append('unlinked_product')
            c.execute('SELECT inventory_id,stock_quantity,warehouse_location FROM inventory WHERE tenant_id=%s AND product_id=%s ORDER BY inventory_id FOR UPDATE',(tenant,pid));stock=c.fetchall()
            c.execute('SELECT source_id,inventory_observation_id,inventory_id,canonical_hash,authority_decision_id FROM keel_provider_stock_posts WHERE tenant_id=%s AND canonical_product_id=%s ORDER BY created_at DESC LIMIT 1',(tenant,pid));prior=c.fetchone()
            c.execute('SELECT authority_decision_id,decision FROM keel_inventory_authority_decisions WHERE tenant_id=%s AND canonical_product_id=%s ORDER BY decided_at DESC LIMIT 1',(tenant,pid));authority=c.fetchone()
        if stock and (not prior or str(prior[0])!=source or len(stock)!=1 or str(prior[2])!=str(stock[0][0]) or prior[3]!=digest(stock)):reasons.append('stock_conflict')
        if authority and authority[1]=='select' and (not prior or str(authority[0])!=str(prior[4])):reasons.append('authority_conflict')
        if prior:
            with conn.cursor() as c:c.execute('SELECT provider_record_identity_id,provider_location_identity_id,quantity_semantics FROM keel_inventory_observations WHERE tenant_id=%s AND inventory_observation_id=%s',(tenant,prior[1]));selected=c.fetchone()
            if selected!=(identity,location,semantics):reasons.append('authority_conflict')
    try:products.InventoryUpdateRequest(stock_quantity=quantity)
    except ValueError:reasons.append('unsupported_stock')
    warehouse=('WooCommerce:'+source) if provider=='woocommerce' else ('Shopify:'+source+':'+str(provider_location).rsplit('/',1)[-1])
    result={'observation_id':observation,'product_id':str(pid) if pid else None,'provider':provider,'identity_id':str(identity),'provider_location_identity_id':str(location) if location else None,'quantity_semantics':semantics,'quantity':str(quantity),'warehouse':warehouse,'previous':str(stock[0][1]) if len(stock)==1 else None,'reasons':sorted(set(reasons)),'eligible':not reasons,'already_applied':bool(prior and str(prior[1])==observation and not reasons)}
    result['preview_hash']=digest(result);return result


def list_review(conn,tenant,source):
    with conn.cursor() as c:
        c.execute('SELECT public.keel_provider_catalog_source_guard(%s)',(source,))
        if not c.fetchone()[0]:raise HTTPException(404,'Active verified source not found.')
        c.execute("SELECT DISTINCT m.inventory_observation_id FROM keel_provider_stock_scan_members m JOIN ingestion_jobs j ON j.tenant_id=m.tenant_id AND j.job_id=m.ingestion_job_id WHERE m.tenant_id=%s AND m.source_id=%s AND j.job_status='COMPLETED' AND j.job_id=(SELECT n.job_id FROM ingestion_jobs n WHERE n.tenant_id=j.tenant_id AND n.source_id=j.source_id AND n.job_status='COMPLETED' ORDER BY n.created_at DESC,n.job_id DESC LIMIT 1) ORDER BY m.inventory_observation_id LIMIT 100",(tenant,source));ids=[str(x[0]) for x in c.fetchall()]
    return {'items':[describe(conn,tenant,source,x) for x in ids],'limit':100,'automatic_merge':False}


def confirm(conn,tenant,actor,source,observation,preview_hash):
    products._require_catalog_admin(conn,tenant,actor)
    plan=describe(conn,tenant,source,observation)
    if plan['already_applied']:return {'product_id':plan['product_id'],'replayed':True,'canonical_write_performed':False}
    if plan['preview_hash']!=preview_hash:raise HTTPException(409,'Source stock or selected inventory changed. Review again.')
    if not plan['eligible']:raise HTTPException(409,{'findings':plan['reasons']})
    location=None
    if plan['provider']=='shopify':
        with conn.cursor() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-stock-location:'+tenant+':'+plan['warehouse'],))
            c.execute('SELECT canonical_location_id FROM keel_inventory_locations WHERE tenant_id=%s AND location_key=%s',(tenant,plan['warehouse']));existing=c.fetchone()
        location=str(existing[0]) if existing else register_canonical_inventory_location(conn,plan['warehouse'],plan['warehouse'])
        decide_provider_location_association(conn,source,plan['provider_location_identity_id'],'associate',location,'owner_confirmed_stock')
    authority=decide_inventory_authority(conn,canonical_product_id=plan['product_id'],quantity_semantics=plan['quantity_semantics'],decision='select',authority_kind='provider',canonical_location_id=location,source_id=source,provider=plan['provider'],provider_record_identity_id=plan['identity_id'],provider_location_identity_id=plan['provider_location_identity_id'],evidence_code='owner_confirmed_stock')
    products.upsert_inventory(conn,tenant,plan['product_id'],stock_quantity=Decimal(plan['quantity']))
    with conn.cursor() as c:
        c.execute('UPDATE inventory SET warehouse_location=%s WHERE tenant_id=%s AND product_id=%s',(plan['warehouse'],tenant,plan['product_id']))
        c.execute('SELECT inventory_id,stock_quantity,warehouse_location FROM inventory WHERE tenant_id=%s AND product_id=%s ORDER BY inventory_id',(tenant,plan['product_id']));stock=c.fetchall();assert len(stock)==1
        c.execute('INSERT INTO keel_provider_stock_posts(tenant_id,source_id,inventory_observation_id,canonical_product_id,inventory_id,actor_id,authority_decision_id,canonical_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(tenant,source,observation,plan['product_id'],stock[0][0],actor,authority,digest(stock)))
    return {'product_id':plan['product_id'],'replayed':False,'canonical_write_performed':True}
