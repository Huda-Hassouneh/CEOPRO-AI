"""Operator-only Paddle TEST catalog reconciliation; no runtime installation.

Source is the same persisted owner-authored Standard catalog as Stripe. A durable
submission is never repeated, even after an empty discovery result or a crash.
No database transaction is kept open across provider calls. The caller supplies
an authenticated Platform Owner and a separately authorized installer socket.
"""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import re
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor
from src.ai.billing import payment_contracts as C
from src.ai.billing.paddle_gateway import BoundPaddleTransport, free_card_trial, _bound_namespace, _bound_request
from scripts.billing_verification import is_test_database_name


class CatalogBlocked(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str,allow_nan=False).encode()).hexdigest()


def validate_manifest(v):
    if (type(v) is not dict or v.get('provider')!='paddle' or v.get('environment')!='test'
            or v.get('tax_category')!='saas' or v.get('tax_mode')!='external'):
        raise CatalogBlocked('Explicit Sandbox SaaS/external-tax approval required')
    for k in ('binding_id','merchant_account_id','provider_operations_authorization','merchant_approval_reference','reason','database'):
        if type(v.get(k)) is not str or not v[k].strip():raise CatalogBlocked('Reviewed catalog authorization required')
    plans=v.get('plan_keys')
    if (type(plans) is not list or not plans or any(type(k) is not str or not k.strip() for k in plans)
            or len(plans)!=len(set(plans))):raise CatalogBlocked('Explicit unique Standard plan selection required')
    prices=v.get('price_ids')
    if (type(prices) is not list or not prices
            or any(type(k) is not str for k in prices)):
        raise CatalogBlocked('Explicit unique persisted price selection required')
    try:
        if any(str(UUID(k))!=k for k in prices) or len(prices)!=len(set(prices)):raise ValueError()
    except ValueError:
        raise CatalogBlocked('Explicit unique persisted price selection required') from None
    if not is_test_database_name(v['database']):raise CatalogBlocked('Isolated TEST database required')
    return C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,v['merchant_account_id'],v['binding_id'])


def price_payload(row, product_id, marker):
    amount=Decimal(str(row['amount']))
    if (row['currency'] not in ('USD','EUR','GBP') or not amount.is_finite() or amount<=0
            or amount*100!=(amount*100).to_integral_value()
            or type(row['interval_months']) is not int or row['interval_months'] not in (1,3,6,12)
            or type(row['trial_days']) is not int or row['trial_days']!=14):
        raise CatalogBlocked('Unsupported persisted price, interval or trial; no rounding/defaults')
    return dict(product_id=product_id,description=f"KEEL {row['display_name']} ({row['period_code']})",
        billing_cycle=dict(interval='month',frequency=row['interval_months']),
        trial_period=dict(interval='day',frequency=row['trial_days'],requires_payment_method=True),
        tax_mode='external',unit_price=dict(amount=str(int(amount*100)),currency_code=row['currency']),
        quantity=dict(minimum=1,maximum=1),custom_data=marker)


class PaddleCatalogTransport(BoundPaddleTransport):
    """Catalog-only extension. Runtime Customer/Checkout transport is unchanged."""
    def request(self,method,path,body=None,*,params=None):
        if path=='/account' and method=='GET':return super().request(method,path,body,params=params)
        if (method not in ('GET','POST') or not re.fullmatch(r'/(products(?:/pro_[a-z0-9]{26})?|prices(?:/pri_[a-z0-9]{26})?)',path)
                or method=='POST' and path not in ('/products','/prices')):
            raise CatalogBlocked('Unsupported catalog operation')
        listing=method=='GET' and path in ('/products','/prices')
        if listing:
            if not params or set(params)-{'after','per_page','status','product_id'}:raise CatalogBlocked('Invalid catalog pagination')
        elif params is not None:raise CatalogBlocked('Unsupported catalog query')
        try:
            response=self._client.request(method,self.origin+path,json=body,params=params,
                headers={'Authorization':'Bearer '+self._key,'Paddle-Version':'1'},timeout=5,follow_redirects=False)
            if response.status_code not in ((200,201) if method=='POST' else (200,)):raise ValueError()
            value=response.json();data=value['data']
            if listing:
                more=value['meta']['pagination']['has_more']
                if type(data) is not list or type(more) is not bool:raise ValueError()
                return dict(items=data,has_more=more)
            if type(data) is not dict:raise ValueError()
            return data
        except Exception:
            raise CatalogBlocked('Catalog read unavailable' if method=='GET' else 'Catalog outcome unknown; recovery only') from None


class CatalogAdapter:
    def __init__(self,binding,transport):
        if binding.provider!='paddle' or binding.environment is not C.GatewayEnvironment.TEST or transport.binding!=binding:
            raise CatalogBlocked('Original Sandbox catalog binding required')
        self.binding,self.transport=binding,transport

    def namespace(self):
        _bound_namespace(self.binding,self.transport)

    def request(self,method,path,body=None,*,params=None):
        return _bound_request(self.binding,self.transport,method,path,body,params=params)

    def list(self,kind,product_id=None):
        rows=[];seen=set();after=None
        for _ in range(1000):
            params=dict(status='active,archived',per_page=50)
            if after:params['after']=after
            if product_id:params['product_id']=product_id
            page=self.request('GET','/'+kind+'s',params=params)
            batch=page['items']
            if type(batch) is not list or type(page['has_more']) is not bool:raise CatalogBlocked('Incomplete catalog discovery')
            for row in batch:
                identifier=row['id']
                if not re.fullmatch(('pro' if kind=='product' else 'pri')+r'_[a-z0-9]{26}',identifier) or identifier in seen:
                    raise CatalogBlocked('Conflicting catalog pagination')
                seen.add(identifier);rows.append(row)
            if not page['has_more']:return rows
            if not batch:raise CatalogBlocked('Incomplete catalog discovery')
            after=batch[-1]['id']
        raise CatalogBlocked('Catalog discovery bound exceeded')

    @staticmethod
    def validate(kind,obj,request):
        if (not re.fullmatch(('pro' if kind=='product' else 'pri')+r'_[a-z0-9]{26}',obj.get('id',''))
                or obj.get('status')!='active' or obj.get('type','standard')!='standard'):
            raise CatalogBlocked('Inactive or unsupported catalog object')
        for k,value in request.items():
            if k=='trial_period':
                if not free_card_trial(obj.get(k),value['frequency']):raise CatalogBlocked('Trial drift')
            elif obj.get(k)!=value:raise CatalogBlocked('Original catalog object drift')
        if kind=='price' and obj.get('unit_price_overrides'):raise CatalogBlocked('Localized prices unsupported')

    def discover(self,kind,request):
        rows=self.list(kind,request.get('product_id'))
        key=request['custom_data']['keel_catalog_key']
        candidates=[r for r in rows if (r.get('custom_data') or {}).get('keel_catalog_key')==key]
        if len(candidates)>1:raise CatalogBlocked('Duplicate catalog identities; manual review required')
        if candidates:
            self.validate(kind,candidates[0],request);return candidates[0]
        # A manually created lookalike is never silently duplicated or rebound.
        for r in rows:
            if kind=='product' and r.get('name')==request['name']:
                raise CatalogBlocked('Unbound matching product requires review')
            if kind=='price' and r.get('product_id')==request['product_id'] and r.get('unit_price')==request['unit_price'] and r.get('billing_cycle')==request['billing_cycle']:
                raise CatalogBlocked('Unbound matching price requires review')
        return None


class CatalogRepository:
    def __init__(self,conn,owner,workspace,manifest):
        self.conn,self.owner,self.workspace,self.manifest=conn,str(UUID(str(owner))),str(UUID(str(workspace))),manifest
        self.binding=validate_manifest(manifest)

    def authorize(self):
        with self.conn.cursor() as q:
            q.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('keel_platform_authority',0))")
            if not q.fetchone()[0]:raise CatalogBlocked('Platform authority busy; retry later')
            q.execute("""SELECT 1 FROM public.keel_platform_members m CROSS JOIN public.keel_platform_workspace w
              JOIN public.users u ON u.user_id=%s
              WHERE m.user_id=u.user_id AND m.role_key='owner' AND m.status='active' AND w.tenant_id=%s
              AND u.platform_disabled_at IS NULL AND public.keel_active_principal(m.user_id,w.tenant_id)""",(self.owner,self.workspace))
            if not q.fetchone():raise CatalogBlocked('Current authenticated Platform Owner required')
            q.execute("SELECT provider,environment,merchant_account_id FROM public.billing_gateway_bindings WHERE binding_id=%s",(self.binding.binding_id,))
            if q.fetchone()!=('paddle','test',self.binding.merchant_account_id):raise CatalogBlocked('Original installed Sandbox binding required')
            q.execute('SELECT current_database()')
            if q.fetchone()[0]!=self.manifest['database']:raise CatalogBlocked('Original isolated catalog database required')

    def rows(self):
        with self.conn.cursor(cursor_factory=RealDictCursor) as q:
            q.execute("""SELECT p.price_id,p.plan_key,u.display_name,p.period_code,p.interval_months,p.amount,p.currency,u.trial_days
             FROM public.billing_plan_prices p JOIN public.usage_plans u USING(plan_key)
             WHERE p.retired_at IS NULL AND u.self_serve AND u.is_active AND u.plan_key=ANY(%s)
               AND p.price_id=ANY(%s::uuid[])
             ORDER BY u.tier_level,p.interval_months,p.price_id""",(self.manifest['plan_keys'],self.manifest['price_ids']))
            rows=[dict(r,price_id=str(r['price_id'])) for r in q.fetchall()]
        if ({r['price_id'] for r in rows}!=set(self.manifest['price_ids'])
                or {r['plan_key'] for r in rows}!=set(self.manifest['plan_keys'])):
            raise CatalogBlocked('Every selected price must belong to the selected active self-serve plans')
        return rows

    def snapshot(self):
        self.authorize();rows=self.rows();self.conn.commit()
        if {r['plan_key'] for r in rows}!=set(self.manifest['plan_keys']):raise CatalogBlocked('Every selected plan must be active, self-serve and priced')
        for row in rows:price_payload(row,'pro_'+'0'*26,{})
        return rows,digest(dict(binding=self.binding.binding_id,merchant=self.binding.merchant_account_id,
            tax_category=self.manifest['tax_category'],tax_mode=self.manifest['tax_mode'],rows=rows))

    def review(self,expected):
        self.authorize()
        rows=self.rows()
        current=digest(dict(binding=self.binding.binding_id,merchant=self.binding.merchant_account_id,
            tax_category=self.manifest['tax_category'],tax_mode=self.manifest['tax_mode'],rows=rows))
        if current!=expected:raise CatalogBlocked('Owner terms changed; review fresh plan')

    @contextmanager
    def lock(self):
        # Same session lock as Stripe sync/publication; no row/transaction locks
        # cross the network. A second process gets an explicit recoverable error.
        with self.conn.cursor() as q:
            q.execute("SELECT pg_try_advisory_lock(hashtextextended('keel_stripe_catalog_sync',0))")
            if not q.fetchone()[0]:raise CatalogBlocked('Catalog publisher busy; retry later')
        self.conn.commit()
        try:yield
        finally:
            self.conn.rollback()
            with self.conn.cursor() as q:q.execute("SELECT pg_advisory_unlock(hashtextextended('keel_stripe_catalog_sync',0))")
            self.conn.commit()

    def read(self,kind,key):
        with self.conn.cursor(cursor_factory=RealDictCursor) as q:
            q.execute('SELECT * FROM public.billing_catalog_operations WHERE binding_id=%s AND entity_kind=%s AND entity_key=%s',
                      (self.binding.binding_id,kind,key));row=q.fetchone()
        self.conn.commit();return dict(row) if row else None

    def prepare(self,kind,key,request,price_id=None):
        self.authorize()
        with self.conn.cursor() as q:
            q.execute("""INSERT INTO public.billing_catalog_operations(binding_id,entity_kind,entity_key,price_id,request,approved_by,approval_reference)
              VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(binding_id,entity_kind,entity_key) DO NOTHING""",
              (self.binding.binding_id,kind,key,price_id,Json(request),self.owner,self.manifest['provider_operations_authorization']))
        self.conn.commit();return self.read(kind,key)

    def claim(self,operation,expected):
        self.review(expected)
        with self.conn.cursor() as q:
            q.execute("UPDATE public.billing_catalog_operations SET state='submitted' WHERE operation_id=%s AND state='prepared' RETURNING operation_id",(str(operation['operation_id']),))
            elected=q.fetchone()
        self.conn.commit()
        if not elected:raise CatalogBlocked('Catalog send already elected; recovery only')

    def finish(self,operation,obj,expected):
        self.review(expected)
        with self.conn.cursor() as q:
            if operation['entity_kind']=='price':
                q.execute("SELECT provider_price_id FROM public.billing_price_references WHERE binding_id=%s AND price_id=%s",(self.binding.binding_id,str(operation['price_id'])))
                old=q.fetchone()
                if old and old[0]!=obj['id']:raise CatalogBlocked('Immutable provider price mapping conflict')
                if not old:q.execute("INSERT INTO public.billing_price_references(binding_id,price_id,provider_price_id,provenance) VALUES(%s,%s,%s,%s)",
                    (self.binding.binding_id,str(operation['price_id']),obj['id'],'catalog:'+str(operation['operation_id'])))
            q.execute("UPDATE public.billing_catalog_operations SET state='succeeded',provider_object_id=%s WHERE operation_id=%s AND state IN ('prepared','submitted')",(obj['id'],str(operation['operation_id'])))
            q.execute("INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,new_value,reason,outcome) VALUES(%s,'owner','paddle_catalog_bind',%s,%s,%s,'succeeded')",
                (self.owner,self.binding.binding_id,Json(dict(operation_id=str(operation['operation_id']),provider_object_id=obj['id'])),self.manifest['reason']))
        self.conn.commit()

    def mapping(self,price_id):
        with self.conn.cursor() as q:
            q.execute('SELECT provider_price_id FROM public.billing_price_references WHERE binding_id=%s AND price_id=%s',(self.binding.binding_id,price_id));r=q.fetchone()
        self.conn.commit();return r[0] if r else None


def synchronize(repo,adapter,*,expected,apply=False):
    if adapter.binding!=repo.binding:raise CatalogBlocked('Original adapter binding required')
    with repo.lock():
        rows,current=repo.snapshot()
        if current!=expected:raise CatalogBlocked('Reviewed catalog digest required')
        # Real namespace check before any catalog request. No capability claims.
        adapter.namespace()
        results=[]
        def entity(kind,key,request,price_id=None):
            marker=dict(keel_catalog_key=digest(dict(binding=repo.binding.binding_id,merchant=repo.binding.merchant_account_id,
                environment='test',kind=kind,key=key)),keel_binding_id=repo.binding.binding_id,keel_environment='test')
            request=dict(request,custom_data=marker)
            op=repo.read(kind,key)
            if op and op['request']!=request:raise CatalogBlocked('Frozen catalog request changed')
            found=adapter.discover(kind,request)
            if price_id:
                mapped=repo.mapping(price_id)
                if mapped and (found is None or mapped!=found['id']):raise CatalogBlocked('Original price mapping conflict; no creation')
            if op and op['state']=='succeeded':
                if found is None or found['id']!=op['provider_object_id']:raise CatalogBlocked('Recorded catalog object missing or rebound')
                if price_id and repo.mapping(price_id)!=found['id']:raise CatalogBlocked('Recorded price mapping missing or conflicting')
                results.append(dict(kind=kind,key=key,state='verified'));return found['id']
            if not apply:
                results.append(dict(kind=kind,key=key,state='adopt' if found else 'pending' if op and op['state']=='submitted' else 'create'))
                return found['id'] if found else None
            if op is None:op=repo.prepare(kind,key,request,price_id)
            if op['request']!=request:raise CatalogBlocked('Frozen catalog request changed during preparation')
            if found is None:
                if op['state']!='prepared':raise CatalogBlocked('Submitted catalog object unresolved; GET recovery only, never resubmit')
                repo.claim(op,expected)
                found=adapter.request('POST','/'+kind+'s',request)
                adapter.validate(kind,found,request)
            repo.finish(op,found,expected)
            results.append(dict(kind=kind,key=key,state='mapped'));return found['id']
        products={}
        for row in rows:
            key=row['plan_key']
            if key not in products:
                products[key]=entity('product','plan:'+key,dict(name='KEEL '+row['display_name'],tax_category=repo.manifest['tax_category']))
            if products[key]:
                payload=price_payload(row,products[key],{})
                entity('price','price:'+row['price_id'],payload,row['price_id'])
        return dict(catalog_digest=current,actions=results,subscriptions_unchanged=True)
