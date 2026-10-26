"""Explicit owner-confirmed source catalog posting via existing product/association authorities.
No provider calls, price overwrites, stock writes or new accounting authority.
"""
import hashlib,json,re
from decimal import Decimal,InvalidOperation
from fastapi import HTTPException
from src.ai.core import usage
from src.ai.extraction.product_identity import normalize_sku,normalize_reference,match_reference
from src.ai.routers import products
from src.market_scraper.provider_identity import associate_provider_record
from src.market_scraper.provider_business_staging import decide_provider_business_review

def _snapshot(conn,tenant,source,revision):
    with conn.cursor() as c:
        c.execute('SELECT public.keel_provider_catalog_revision_guard(%s,%s)',(source,revision))
        if not c.fetchone()[0]:raise HTTPException(404,'No active verified source.')
        c.execute("SELECT b.provider_record_identity_id,b.entity_type,b.typed_values,b.validation_findings,b.validation_status,i.provider,i.parent_identity_id,i.canonical_product_id,i.mapping_status,i.current_revision_sha256,b.provider_identity_revision_sha256,r.decision FROM keel_provider_business_revisions b JOIN keel_provider_record_identities i ON i.tenant_id=b.tenant_id AND i.provider_record_identity_id=b.provider_record_identity_id JOIN keel_provider_sources ps ON ps.tenant_id=b.tenant_id AND ps.source_id=b.source_id JOIN data_sources ds ON ds.tenant_id=b.tenant_id AND ds.source_id=b.source_id JOIN ingestion_jobs j ON j.tenant_id=b.tenant_id AND j.job_id=b.ingestion_job_id LEFT JOIN keel_provider_business_reviews r ON r.tenant_id=b.tenant_id AND r.business_revision_id=b.business_revision_id WHERE b.tenant_id=%s AND b.source_id=%s AND b.business_revision_id=%s AND ds.is_active AND ds.policy_status='ALLOWED' AND ps.connection_state='verified' AND j.job_status='COMPLETED' AND NOT EXISTS(SELECT 1 FROM keel_provider_business_revisions n WHERE n.tenant_id=b.tenant_id AND n.provider_record_identity_id=b.provider_record_identity_id AND n.revision_number>b.revision_number)",(tenant,source,revision))
        row=c.fetchone()
    if not row:raise HTTPException(404,'No current, completed record from an active verified source.')
    identity,entity,values,findings,validation,provider,parent,associated,state,current_hash,value_hash,review=row
    if current_hash!=value_hash:raise HTTPException(409,'Provider identity changed. Synchronize and review its latest revision.')
    reasons=[]
    if entity not in ('product','variant') or (provider=='shopify' and entity=='product') or (provider=='woocommerce' and entity=='product' and values.get('product_type') not in ('simple',None)):reasons.append('unsupported_entity')
    if validation=='invalid' or review=='reject' or state in ('conflict','unavailable'):reasons.append('validation_review')
    if any(x.get('field')!='provider_identity' or x.get('code')!='pending_review' for x in findings):reasons.append('validation_review')
    title=values.get('title')
    if provider=='shopify' and entity=='variant' and parent:
        with conn.cursor() as c:
            c.execute("SELECT typed_values->>'title' FROM keel_provider_business_revisions WHERE tenant_id=%s AND provider_record_identity_id=%s ORDER BY revision_number DESC LIMIT 1",(tenant,parent));p=c.fetchone()
        if p and p[0]:title=p[0] if title in ('Default Title',None,'') else p[0]+' / '+title
    if not isinstance(title,str) or not title.strip() or len(title)>250:reasons.append('canonical_title')
    try:sku=normalize_sku(values.get('sku'))
    except ValueError:sku=None;reasons.append('sku_format')
    money=values.get('price');amount=money.get('amount') if isinstance(money,dict) else money
    currency=money.get('currency_code') if isinstance(money,dict) else values.get('currency_code')
    try:
        price=Decimal(str(amount))
        if not price.is_finite() or price<0 or price>=100000000 or price.normalize().as_tuple().exponent < -4:raise ValueError()
    except (InvalidOperation,ValueError,TypeError):price=None;reasons.append('source_price')
    with conn.cursor() as c:
        c.execute('SELECT primary_currency,supported_currencies FROM companies WHERE tenant_id=%s',(tenant,));company=c.fetchone()
    if not company or currency not in [company[0],*(company[1] or [])]:reasons.append('unsupported_currency')
    barcode=values.get('barcode') or None
    try:barcode=products.normalize_barcode(barcode)
    except ValueError:reasons.append('barcode_invalid');barcode=None
    with conn.cursor() as c:
        c.execute('SELECT product_id,product_name,sku,metadata,version FROM products WHERE tenant_id=%s AND deleted_at IS NULL ORDER BY product_id',(tenant,));catalog=c.fetchall()
    matches=[]
    for pid,name,existing_sku,metadata,version in catalog:
        labels=[name] if isinstance(name,str) else list((name or {}).values())
        if (sku and existing_sku and sku.lower()==existing_sku.lower()) or (title and any(isinstance(v,str) and normalize_reference(v)==normalize_reference(title) for v in labels)) or (barcode and (metadata or {}).get('barcode') and barcode.zfill(14)==str(metadata['barcode']).zfill(14)):
            matches.append({'id':str(pid),'name':name,'sku':existing_sku,'version':version})
    if associated:
        target=next((x for x in catalog if str(x[0])==str(associated)),None)
        if target is None:reasons.append('associated_product_unavailable')
        action='linked';target_id=str(associated)
    else:
        reference={'product_name':title,**({'sku':sku} if sku else {}),**({'barcode':barcode} if barcode else {})}
        resolved=match_reference(reference,[{'product_id':str(p),'product_name':n,'sku':s,'metadata':m} for p,n,s,m,_ in catalog])
        if resolved['status']=='matched':action='link';target_id=resolved['product_id']
        elif resolved['status']=='missing':action='create';target_id=None
        else:
            action='review';target_id=None;reasons.append('identity_conflict')
    material={'revision':revision,'identity':str(identity),'action':action,'target':target_id,'title':title,'sku':sku,'price':str(price) if price is not None else None,'currency':currency,'barcode':barcode,'matches':matches,'reasons':reasons,'review_decision':review}
    digest=hashlib.sha256(json.dumps(material,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    return {**material,'preview_hash':digest,'eligible':not reasons,'canonical_write_performed':False}

def preview(conn,tenant,source,revision):return _snapshot(conn,tenant,source,revision)

def confirm(conn,tenant,actor,source,revision,preview_hash):
    products._require_catalog_admin(conn,tenant,actor)
    with conn.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-catalog:'+tenant,))
    # Serialize canonical candidate creation with the existing live-capacity authority.
    usage.lock_feature(conn,tenant,usage.TRACKED_PRODUCTS)
    snapshot=_snapshot(conn,tenant,source,revision)
    if snapshot['action']=='linked' and snapshot['eligible']:
        return {'product_id':snapshot['target'],'status':'linked','created':False,'canonical_write_performed':False}
    if snapshot['preview_hash']!=preview_hash:raise HTTPException(409,'Source or catalog changed. Preview again before confirming.')
    if not snapshot['eligible']:raise HTTPException(409,{'message':'Source product needs review.','findings':snapshot['reasons']})
    if snapshot['review_decision'] is None:
        decide_provider_business_review(conn,revision,decision='approve',idempotency_key='catalog:'+revision,reason_code='owner_confirmed_catalog_post')
    target=snapshot['target'];created=False
    if snapshot['action']=='create':
        usage.ensure_capacity(conn,tenant,usage.TRACKED_PRODUCTS,1)
        product=products.create_product(conn,tenant,actor,{'en':snapshot['title']},None,None,None,Decimal(snapshot['price']),None,snapshot['currency'],barcode=snapshot['barcode'],sku=snapshot['sku'])
        target=product['product_id'];created=True
        with conn.cursor() as c:c.execute("UPDATE products SET source='IMPORTED',metadata=coalesce(metadata,'{}')||jsonb_build_object('provider_source_id',%s::text,'provider_identity_id',%s::text) WHERE tenant_id=%s AND product_id=%s",(source,snapshot['identity'],tenant,target))
    associate_provider_record(conn,snapshot['identity'],'product',target,reason_code='owner_confirmed_catalog_post',evidence_reference=revision)
    return {'product_id':target,'status':'linked','created':created,'canonical_write_performed':created}
