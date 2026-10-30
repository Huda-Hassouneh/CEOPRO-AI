"""Restricted owner repository adapter reusing the existing promotion business authority."""
from datetime import datetime,timezone
from psycopg2.extras import Json
from src.ai.billing import promotions
from src.ai.billing.promotions import PromotionError

def command(conn,action,payload=None):
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT public.billing_owner_promotion_command(%s,%s::jsonb)',(action,Json(payload or {})))
            return cur.fetchone()[0]
    except Exception as exc:
        code=getattr(exc,'pgcode',None)
        mapped={'42501':(403,'platform_owner_required','Active Platform Owner permission is required.'),'P0002':(404,'promotion_not_found','Promotion definition not found.'),'55000':(409,'promotion_state_changed','The promotion revision changed. Refresh before retrying.'),'22023':(422,'invalid_promotion_terms','Promotion terms or provider mapping are invalid.')}
        if code in mapped:raise PromotionError(*mapped[code]) from None
        raise

def list_definitions(conn,actor_user_id):
    rows=command(conn,'list')['items']
    for row in rows:row['missing_terms']=sorted(promotions.TERMS_REQUIRED-row['terms'].keys())
    return rows

def save_draft(conn,*,actor_user_id,code,name,description,terms,plan_keys,reason,promotion_id=None):
    code=promotions.normalize_code(code)
    if promotion_id:
        old=command(conn,'get',{'promotion_id':promotion_id})
        if old['status']!='draft':raise PromotionError(409,'promotion_not_editable','Only draft promotion definitions can be edited.')
        terms={**old['terms'],**terms}
    normalized,missing=promotions._validate_terms(terms)
    plans=sorted(set(plan_keys or []))
    if not plans:missing.append('plan_keys')
    result=command(conn,'save_draft',{'promotion_id':promotion_id,'code':code,'name':name.strip(),'description':description,'terms':normalized,'plan_keys':plans,'reason':reason})
    return {**result,'missing_terms':sorted(set(missing)),'eligible':False}

def disable(conn,*,actor_user_id,promotion_id,reason):
    row=command(conn,'get',{'promotion_id':promotion_id})
    if row['status']=='disabled':return {'promotion_id':promotion_id,'status':'disabled'}
    if row['status']=='active' and row.get('stripe_promotion_code_id'):
        if not promotions._provider_mutations_allowed():raise PromotionError(503,'promotion_provider_mode_blocked','Provider deactivation requires Stripe TEST credentials.')
        try:promotions.stripe_api.deactivate_promotion_code(row['stripe_promotion_code_id'])
        except promotions.stripe_api.PaymentsNotConfigured:raise PromotionError(503,'payments_not_configured','Stripe is not configured.') from None
        except Exception:raise PromotionError(502,'promotion_provider_error','Stripe could not deactivate the promotion. No local status was changed.') from None
    result=command(conn,'disable',{'promotion_id':promotion_id,'reason':reason})
    return {'promotion_id':promotion_id,'status':result['status']}

def activate(conn,*,actor_user_id,promotion_id,approval_reference,reason):
    if not promotions.enabled():raise PromotionError(503,'promotions_unavailable','Managed promotions are disabled by configuration.')
    if not promotions._provider_mutations_allowed():raise PromotionError(503,'promotion_provider_mode_blocked','Promotion activation requires Stripe TEST credentials.')
    approval_reference=(approval_reference or '').strip();reason=(reason or '').strip()
    if not approval_reference or len(approval_reference)>255 or not reason or len(reason)>2000:raise PromotionError(422,'promotion_approval_required','An approval reference and audit reason are required.')
    row=command(conn,'get',{'promotion_id':promotion_id})
    if row['status']=='active':return {'promotion_id':promotion_id,'code':row['code'],'status':'active','reused':True}
    if row['status'] not in {'draft','disabled'}:raise PromotionError(409,'promotion_not_editable','Promotion cannot be activated in this state.')
    terms={**row['terms'],'stripe_coupon_id':row.get('stripe_coupon_id') or row['terms'].get('stripe_coupon_id'),'stripe_promotion_code_id':row.get('stripe_promotion_code_id') or row['terms'].get('stripe_promotion_code_id')}
    normalized,missing=promotions._validate_terms(terms)
    required=promotions.TERMS_REQUIRED-{'stripe_coupon_id','stripe_promotion_code_id'}
    missing=sorted(set(missing)-{'stripe_coupon_id','stripe_promotion_code_id'})
    if missing or not required.issubset(normalized):raise PromotionError(422,'promotion_terms_incomplete','Complete the promotion terms before activation.')
    if normalized.get('discount_type')=='fixed_amount' and not normalized.get('currency'):raise PromotionError(422,'promotion_terms_incomplete','Currency is required for a fixed discount.')
    if normalized.get('expires_at') and datetime.fromisoformat(normalized['expires_at'])<=datetime.now(timezone.utc):raise PromotionError(422,'promotion_expired','An expired promotion cannot be activated.')
    if not row['plan_keys']:raise PromotionError(422,'promotion_plans_required','Link at least one active plan before activation.')
    _,_,normalized=promotions.verified_provider_mapping(row['code'],row['name'],row['status'],normalized,row['plan_keys'],terms['stripe_coupon_id'],terms['stripe_promotion_code_id'])
    # JSON equality is verified in SQL while holding the same owner authority lock.
    result=command(conn,'activate',{'promotion_id':promotion_id,'terms':normalized,'expected_status':row['status'],'expected_terms':row['terms'],'approval_reference':approval_reference,'reason':reason})
    return {'promotion_id':promotion_id,'code':result['code'],'status':result['status'],'reused':False}
