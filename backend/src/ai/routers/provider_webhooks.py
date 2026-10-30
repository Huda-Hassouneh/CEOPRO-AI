"""Public provider delivery intake; authentication is the exact-body provider HMAC."""
import os
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
import psycopg2
from src.ai import db
from src.market_scraper.shopify import ShopifyError, UnsafeTargetError, PRIVACY_TOPICS, verify_shopify_webhook, verify_privacy_webhook
from src.market_scraper.provider_lifecycle import authenticate_and_record_shopify_delivery

router=APIRouter(prefix='/onboarding/shopify',tags=['provider webhooks'])
MAX_BODY=2*1024*1024

@router.post('/webhooks/{source_id}')
async def shopify_webhook(source_id:UUID,request:Request):
    secret=os.getenv('SHOPIFY_CLIENT_SECRET','').strip()
    if not secret:raise HTTPException(503,'Shopify webhook authentication is not configured.')
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>MAX_BODY:raise HTTPException(413,'Shopify webhook exceeds the allowed size.')
    raw=bytes(body)
    try:
        # Verify BEFORE cross-tenant identity lookup; no credential or payload lookup.
        verified=verify_shopify_webhook(raw,request.headers,secret,
            expected_shop=request.headers.get('X-Shopify-Shop-Domain',''))
        lookup=db.auth_lookup_connection()
        try:
            with lookup.cursor() as cursor:
                cursor.execute('SELECT * FROM public.keel_shopify_webhook_source(%s,%s)',(str(source_id),verified.shop_domain))
                source=cursor.fetchone()
        finally:lookup.close()
        if not source:raise HTTPException(404,'No registered Shopify delivery source.')
        tenant,shop_id,domain=map(str,source)
        if verified.topic in PRIVACY_TOPICS:
            verify_privacy_webhook(raw,request.headers,secret,expected_shop=domain,expected_shop_id=shop_id)
        conn=db.app_role_connection(tenant,'00000000-0000-0000-0000-000000000000')
        try:
            receipt=authenticate_and_record_shopify_delivery(conn,tenant_id=tenant,source_id=str(source_id),
                raw_body=raw,headers=request.headers,client_secret=secret)
            with conn.cursor() as cursor:
                cursor.execute('SELECT public.keel_shopify_delivery_intake(%s)',(receipt['delivery_receipt_id'],))
                state=cursor.fetchone()[0]
            conn.commit()
            # Acknowledges durable receipt only, never claims sync or privacy erasure.
            return {**receipt,'state':state,'privacy_completed':False,'canonical_write_performed':False}
        except Exception:
            conn.rollback();raise
        finally:conn.close()
    except (ShopifyError,UnsafeTargetError) as exc:
        raise HTTPException(400 if getattr(exc,'code',None)=='unsupported_topic' else 401,'Shopify delivery authentication failed.') from None
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(409,'Shopify delivery identity conflicts with recorded content.') from None
