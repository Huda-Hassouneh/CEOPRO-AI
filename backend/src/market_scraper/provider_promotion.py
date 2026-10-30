"""Disposable-only opt-in reconciliation through the existing canonical services.
Tenant Owner approval is source/category scoped. No parallel posting engine.
Automatic invoice accounting remains policy blocked. Provider scan checkpoint
means evidence persisted, never a claim that all canonical rows were applied.
"""
import os
from fastapi import HTTPException
from psycopg2.extras import Json
from src.market_scraper import provider_catalog,provider_stock
from src.ai.routers.products import _require_catalog_admin,_publish_discovery_request


def test_runtime(conn):
    if os.getenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION')!='YES':return False
    with conn.cursor() as c:
        c.execute("SELECT current_database(),current_user");name,role=c.fetchone()
    # Server address can be a container bridge; verify the actual client socket target.
    parameters=getattr(conn,'_raw',conn).get_dsn_parameters()
    return name.startswith('keel_billing_test_') and parameters.get('dbname')==name and parameters.get('host') in ('127.0.0.1','::1') and role=='ceopro_app'


def settings(conn,tenant,source,actor):
    with conn.cursor() as c:
        c.execute('SELECT public.keel_provider_catalog_source_guard(%s)',(source,))
        if not c.fetchone()[0]:raise HTTPException(404,'Active verified source not found.')
        c.execute("SELECT role_key FROM tenant_users WHERE tenant_id=%s AND user_id=%s AND removed_at IS NULL AND platform_suspended_at IS NULL",(tenant,actor));role=c.fetchone()
        c.execute('SELECT DISTINCT ON (category) category,enabled,decision_id,actor_id,decided_at FROM keel_provider_promotion_decisions WHERE tenant_id=%s AND source_id=%s ORDER BY category,decided_at DESC,decision_id DESC',(tenant,source));rows=c.fetchall()
    enabled={r[0]:r[1] for r in rows}
    return {'disposable_runtime_enabled':test_runtime(conn),'can_change':bool(role and role[0]=='owner'),'categories':{category:enabled.get(category,False) for category in ('catalog','inventory','orders')},'history':[{'category':r[0],'enabled':r[1],'decision_id':str(r[2]),'actor_id':str(r[3]),'decided_at':r[4].isoformat()} for r in rows],'orders_policy':'separate_accounting_mapping_approval_required'}


def decide(conn,tenant,source,actor,category,enabled):
    state=settings(conn,tenant,source,actor)
    if not state['can_change']:raise HTTPException(403,'Only the Tenant Owner can opt in for this source.')
    if not state['disposable_runtime_enabled']:raise HTTPException(409,'Automatic promotion is authorized only in an explicitly enabled disposable test runtime.')
    if category=='orders' and enabled:raise HTTPException(409,'Automatic invoices require separate approval of payment, tax, currency, cancellation and deduplication mappings.')
    with conn.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-optin:'+tenant+':'+source+':'+category,))
        # Re-read after serialization; repeat the same decision without new audit effects.
        state=settings(conn,tenant,source,actor)
        if state['categories'][category]==enabled:return state
        c.execute('SELECT provider FROM keel_provider_sources WHERE tenant_id=%s AND source_id=%s',(tenant,source));provider=c.fetchone()[0]
        c.execute('INSERT INTO keel_provider_promotion_decisions(tenant_id,source_id,provider,category,enabled,actor_id) VALUES(%s,%s,%s,%s,%s,%s) RETURNING decision_id',(tenant,source,provider,category,enabled,actor));did=c.fetchone()[0]
        c.execute("INSERT INTO audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(%s,%s,'PROVIDER_CATEGORY_OPT_IN','keel_provider_promotion_decisions',%s,%s)",(tenant,actor,did,Json({'source_id':source,'category':category,'enabled':enabled})))
    return settings(conn,tenant,source,actor)


def reconcile(conn,tenant,source,actor):
    _require_catalog_admin(conn,tenant,actor)
    state=settings(conn,tenant,source,actor)
    if not state['disposable_runtime_enabled']:conn.rollback();return {'enabled':False,'status':'disabled_by_default'}
    result={'enabled':True,'catalog_created':0,'catalog_linked':0,'stock_updated':0,'held':[],'orders':'POLICY_BLOCKED','status':'completed','truncated':False};publish=False
    if state['categories']['catalog']:
        with conn.cursor() as c:
            c.execute("SELECT b.business_revision_id,b.entity_type,b.provider,b.typed_values->>'product_type' FROM keel_provider_business_revisions b WHERE b.tenant_id=%s AND b.source_id=%s AND b.entity_type IN ('product','variant') AND NOT EXISTS(SELECT 1 FROM keel_provider_business_revisions n WHERE n.tenant_id=b.tenant_id AND n.provider_record_identity_id=b.provider_record_identity_id AND n.revision_number>b.revision_number) ORDER BY b.created_at,b.business_revision_id LIMIT 2001",(tenant,source));rows=c.fetchall()
        conn.commit();result['truncated']=len(rows)>2000
        for revision,entity,provider,kind in rows[:2000]:
            if (provider=='shopify' and entity=='product') or (provider=='woocommerce' and entity=='product' and kind not in ('simple',None)):continue
            try:
                plan=provider_catalog.preview(conn,tenant,source,str(revision))
                if not plan['eligible']:result['held'].append({'revision':str(revision),'findings':plan['reasons']});conn.rollback();continue
                conn.commit()
                # Opt-out and source/category configuration serialize against this posting.
                with conn.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-optin:'+tenant+':'+source+':catalog',))
                if not settings(conn,tenant,source,actor)['categories']['catalog']:conn.rollback();break
                saved=provider_catalog.confirm(conn,tenant,actor,source,str(revision),plan['preview_hash']);conn.commit()
                result['catalog_created']+=bool(saved['created']);result['catalog_linked']+=not saved['created'];publish=publish or saved['created']
            except HTTPException as exc:conn.rollback();result['held'].append({'revision':str(revision),'status':exc.status_code,'findings':['review_required']})
    if state['categories']['inventory']:
        stock=provider_stock.list_review(conn,tenant,source);conn.commit()
        for plan in stock['items']:
            if not plan['eligible']:result['held'].append({'observation':plan['observation_id'],'findings':plan['reasons']});continue
            if plan['already_applied']:continue
            with conn.cursor() as c:c.execute('SELECT 1 FROM keel_provider_stock_posts WHERE tenant_id=%s AND canonical_product_id=%s',(tenant,plan['product_id']));selected=c.fetchone()
            if not selected:conn.rollback();result['held'].append({'observation':plan['observation_id'],'findings':['explicit_source_field_location_selection_required']});continue
            try:
                with conn.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('provider-optin:'+tenant+':'+source+':inventory',))
                if not settings(conn,tenant,source,actor)['categories']['inventory']:conn.rollback();break
                saved=provider_stock.confirm(conn,tenant,actor,source,plan['observation_id'],plan['preview_hash']);conn.commit();result['stock_updated']+=bool(saved['canonical_write_performed'])
            except HTTPException as exc:conn.rollback();result['held'].append({'observation':plan['observation_id'],'status':exc.status_code,'findings':['stock_review_required']})
    if result['held'] or result['truncated']:result['status']='review_required'
    with conn.cursor() as c:c.execute("INSERT INTO audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(%s,%s,'PROVIDER_CANONICAL_RECONCILIATION','data_sources',%s,%s)",(tenant,actor,source,Json(result)))
    conn.commit()
    if publish:_publish_discovery_request(tenant)
    return result
