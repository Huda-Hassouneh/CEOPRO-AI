"""Authenticated Node integration for the existing business insight detectors.

No LLM call, writes, billing mutation or fabricated recommendation. Exact source
selection and daily forecast semantics are included with each finding.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
import os
import hmac
import hashlib
import jwt
from fastapi import APIRouter, Header, HTTPException, Query
from src.ai import db
from src.ai.core.business_time import window_start
from src.ai.insights import pipeline, sales
from src.ai.insights.cross_signal import ProductSignals, detect_insights
from src.ai.insights.category_gap import detect_category_gap_insights
from src.ai.insights.assortment_reduce import detect_reduce_candidate_insights

router=APIRouter()

def node_context(authorization, service_signature):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
    secret=os.getenv('JWT_SECRET')
    if not secret:raise HTTPException(503,'JWT_SECRET is not configured')
    expected=hmac.new(secret.encode(),('keel:business-insights:'+authorization).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,service_signature):raise HTTPException(401,'Authenticated Node service required')
    try:
        claims=jwt.decode(authorization[7:],secret,algorithms=['HS256'],options={'require':['exp']})
        tenant=str(UUID(claims['tenant_id']));user=str(UUID(claims.get('user_id') or claims['id']))
        session=str(UUID(claims['sessionId']))
    except (jwt.PyJWTError,KeyError,TypeError,ValueError):raise HTTPException(401,'Invalid Node session')
    conn=db.app_role_connection(tenant,user)
    try:
        with conn.cursor() as c:
            c.execute("""SELECT sr.permissions FROM auth_sessions s
              JOIN tenant_users tu ON tu.tenant_id=s.tenant_id AND tu.user_id=s.user_id
              JOIN users u ON u.user_id=tu.user_id JOIN system_roles sr ON sr.role_key=tu.role_key
              JOIN companies co ON co.tenant_id=tu.tenant_id
              WHERE s.id=%s AND s.tenant_id=%s AND s.user_id=%s AND s.revoked_at IS NULL AND s.expires_at>now()
                AND tu.removed_at IS NULL AND tu.platform_status='active'
                AND co.deleted_at IS NULL AND co.platform_status='active' AND u.session_version=%s;""",
                      (session,tenant,user,claims.get('sessionVersion',0)))
            row=c.fetchone()
            if not row:raise HTTPException(403,'Active membership and session required')
            permissions=row[0]
            if not any(permissions.get(k) is True for k in ('all','view_analytics','manage_catalog')):raise HTTPException(403,'Recommendation access denied')
        return conn,tenant
    except Exception:
        conn.rollback();conn.close();raise

def _price_sources(conn,tenant):
    with conn.cursor() as c:
        c.execute("""SELECT p.product_id,p.current_price,p.currency,cp.competitor_price_id,m.mapping_id,
          m.global_competitor_id,g.competitor_name,cp.scraped_price,cp.observed_at
          FROM products p JOIN competitor_product_mappings m ON m.tenant_id=p.tenant_id AND m.product_id=p.product_id
          JOIN tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
          JOIN global_competitors g ON g.global_competitor_id=tc.global_competitor_id
          LEFT JOIN data_sources ds ON ds.tenant_id=m.tenant_id AND ds.source_id=m.source_id
          JOIN LATERAL(SELECT * FROM competitor_prices x WHERE x.tenant_id=m.tenant_id AND x.mapping_id=m.mapping_id
            ORDER BY observed_at DESC,competitor_price_id DESC LIMIT 1) cp ON true
          WHERE p.tenant_id=%s AND p.deleted_at IS NULL AND m.is_active AND NOT m.tracking_paused AND m.comparison_confirmed
            AND tc.is_tracked AND cp.currency=p.currency AND cp.scraped_price>0 AND cp.is_available AND cp.is_exact_data
            AND cp.source_status='ALLOWED' AND cp.observed_at BETWEEN now()-interval '30 days' AND now()
            AND (m.source_id IS NULL OR (ds.is_active AND ds.policy_status='ALLOWED'));""",(tenant,))
        result={}
        for pid,ours,currency,pid_price,mid,cid,name,price,at in c.fetchall():
            result.setdefault(str(pid),[]).append({'table':'competitor_prices','record_id':str(pid_price),'mapping_id':str(mid),
                'competitor_id':str(cid),'competitor_name':name,'price':float(price),'currency':currency,
                'observed_at':at.isoformat(),'own_price':float(ours)})
    return result

def _forecasts(conn,tenant):
    with conn.cursor() as c:
        c.execute("""SELECT DISTINCT ON(product_id) product_id,forecast_id,expected_demand,forecast_target_date,created_at
          FROM demand_forecasts WHERE tenant_id=%s AND forecast_target_date>=CURRENT_DATE
            AND created_at BETWEEN now()-interval '30 days' AND now()
          ORDER BY product_id,created_at DESC,forecast_id DESC;""",(tenant,))
        return {str(pid):{'table':'demand_forecasts','record_id':str(fid),'expected_units':float(units),
             'target_date':day.isoformat(),'created_at':at.isoformat(),'prediction_kind':'target_day'}
             for pid,fid,units,day,at in c.fetchall()}

def build_recommendations(conn,tenant,limit=500):
    now=datetime.now(timezone.utc)
    sales_data=sales.trends(conn,tenant,window_start(conn,30),window_start(conn,30,periods=2),now)
    prices=_price_sources(conn,tenant);forecasts=_forecasts(conn,tenant)
    sentiment,business_sentiment=pipeline._load_product_sentiment(conn,tenant)
    with conn.cursor() as c:
        c.execute("SELECT product_id,product_name FROM products WHERE tenant_id=%s AND deleted_at IS NULL;",(tenant,))
        products={str(pid):name for pid,name in c.fetchall()}
        c.execute("""SELECT r.product_id,r.subject_type,r.review_id,s.sentiment_id,r.review_date,s.processed_at
          FROM reviews r JOIN sentiment_results s ON s.tenant_id=r.tenant_id AND s.review_id=r.review_id
          WHERE r.tenant_id=%s AND r.subject_type IN ('PRODUCT','BUSINESS')
            AND r.review_date BETWEEN now()-interval '30 days' AND now() AND r.safety_status='SAFE' AND r.source_status='ALLOWED' ORDER BY r.review_date DESC;""",(tenant,))
        review_sources={};business_reviews=[]
        for pid,kind,rid,sid,at,analysed in c.fetchall():
            record={'table':'sentiment_results','record_id':str(sid),'review_id':str(rid),'observed_at':at.isoformat(),'scope':kind.lower()}
            if kind=='BUSINESS':business_reviews.append(record)
            elif pid:review_sources.setdefault(str(pid),[]).append(record)
    signals=[];proof={}
    for pid,names in products.items():
        name=names.get('en') or names.get('ar') or pid if isinstance(names,dict) else str(names)
        local=prices.get(pid,[]);sale=sales_data.get(pid,{})
        mean=sum(p['price'] for p in local)/len(local) if local else None
        gap=(local[0]['own_price']-mean)/mean*100 if mean else None
        forecast=forecasts.get(pid)
        forecast_change=pipeline._forecast_trend_pct(forecast['expected_units'],1,sale.get('recent_units')) if forecast else None
        signal=ProductSignals(pid,name,gap,sentiment.get(pid,business_sentiment),sale.get('trend_pct'),forecast_change)
        signals.append(signal)
        reviews=review_sources.get(pid,business_reviews)
        proof[pid]={'signals':asdict(signal),'sources':local+([forecast] if forecast else []),
          'sales':sale or None,'feedback':{'record_count':len(reviews),'records_sample':reviews[:20],
          'scope':'product' if pid in review_sources else 'business'},'sales_source_policy':'transactions_preferred_per_product_for_entire_window'}
    snapshot=detect_insights(signals,max_insights=max(len(products)*7,1))
    causal=pipeline.generate_causal_insights_for_tenant(conn,tenant)
    category=detect_category_gap_insights(conn,tenant,max_insights=501)
    reduce=detect_reduce_candidate_insights(conn,tenant,max_insights=501)
    findings=sorted(snapshot+causal+category+reduce,key=lambda i:(-i.confidence,i.product_id,i.rule_id))
    result=[]
    for insight in findings[:limit]:
        rule=insight.rule_id or insight.category
        key=str(uuid5(NAMESPACE_URL,tenant+':'+insight.product_id+':'+rule))
        evidence={**proof.get(insight.product_id,{}),'detector_facts':insight.facts,'generated_at':now.isoformat(),
                  'window_days':30,'causality_proven':False}
        result.append({'logical_key':key,'rule_id':rule,'product_id':insight.product_id or None,
            'product_name':products.get(insight.product_id), 'category':insight.category,
            'priority':'high' if insight.confidence>=.8 else 'medium' if insight.confidence>=.5 else 'low',
            'message':insight.message,'evidence':evidence})
    return {'recommendations':result,'generated_at':now.isoformat(),'complete':len(findings)<=limit,
            'products_checked':len(products),'engine_version':2}

@router.get('/business-recommendations')
def recommendations(limit:int=Query(default=500,ge=1,le=500),authorization:str=Header(default=''),x_keel_insights_signature:str=Header(default='')):
    conn,tenant=node_context(authorization,x_keel_insights_signature)
    try:
        result=build_recommendations(conn,tenant,limit);conn.commit();return result
    except Exception:conn.rollback();raise
    finally:conn.close()
