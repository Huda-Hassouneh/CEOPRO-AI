"""Disabled customer journey. No default service factory or privileged fallback."""
from contextlib import contextmanager
import os
from typing import Literal
from uuid import UUID, uuid5
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai import db
from src.ai.routers.trial_consent import _invoke

router = APIRouter()


@router.post('/trial-journeys/webhook',include_in_schema=False)
async def journey_webhook(request: Request):
    """Dedicated bound TEST signature boundary. Never calls legacy dispatch."""
    if os.getenv('RECURRING_JOURNEY_ENABLED','').lower()!='true':
        raise HTTPException(404,'Journey unavailable')
    decoder=getattr(request.app.state,'subscription_journey_webhook_decoder',None)
    handler=getattr(request.app.state,'subscription_journey_webhook_handler',None)
    if decoder is None or handler is None:
        raise HTTPException(503,'Bound journey webhook unavailable')
    from src.ai.billing.payment_contracts import InvalidPaymentWebhook
    try:event=decoder.decode(await request.body(),request.headers.get('Stripe-Signature'))
    except (InvalidPaymentWebhook,ValueError,TypeError):
        raise HTTPException(400,'Invalid journey signature or binding') from None
    connection=None
    try:
        from src.ai.billing.journey_webhooks import classify
        connection=db.billing_webhook_connection(event.event_id)
        if not classify(connection,event):
            raise ValueError('Unresolved journey association')
        connection.commit()
        return dict(received=True,**handler(event))
    except Exception:
        if connection is not None:connection.rollback()
        raise HTTPException(500,'Journey event pending trusted reconciliation') from None
    finally:
        if connection is not None:connection.close()


@router.post('/trial-journeys/webhook/{provider}',include_in_schema=False)
async def bound_journey_webhook(provider: Literal['stripe','paddle'],request: Request):
    if os.getenv('RECURRING_JOURNEY_ENABLED','').lower()!='true':raise HTTPException(404,'Journey unavailable')
    installed=getattr(request.app.state,'bound_journey_webhooks',{})
    endpoint=installed.get(provider)
    if endpoint is None:raise HTTPException(503,'Bound journey webhook unavailable')
    decoder,handler=endpoint
    if decoder.binding.provider!=provider:raise HTTPException(503,'Webhook binding unavailable')
    from src.ai.billing.payment_contracts import InvalidPaymentWebhook
    try:event=decoder.decode(await request.body(),request.headers.get(decoder.signature_header if provider=='paddle' else 'Stripe-Signature'))
    except (InvalidPaymentWebhook,ValueError,TypeError):raise HTTPException(400,'Invalid journey signature or binding') from None
    # Resolver and SQL enforce the original persisted actor/tenant/binding. This
    # route deliberately has no generic legacy handler, including unknown IDs.
    try:return dict(received=True,**handler(event))
    except Exception:raise HTTPException(500,'Journey event pending trusted reconciliation') from None


class PlanChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID
    plan_key: str = Field(min_length=1,max_length=60)
    period_code: str = Field(min_length=1,max_length=30)


class LanguageChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['en','ar']


@contextmanager
def _journey(request, response, ctx):
    response.headers['Cache-Control']='no-store'
    response.headers['Vary']='Authorization'
    if os.getenv('RECURRING_JOURNEY_ENABLED','').lower()!='true':
        raise HTTPException(404,'Journey unavailable')
    if getattr(ctx,'email_verified',False) is not True:
        raise HTTPException(403,'Verified account required')
    factory = getattr(request.app.state,'subscription_journey_factory',None)
    if factory is None:
        raise HTTPException(503,'Protected journey service unavailable')
    connection=None
    try:
        connection=db.app_role_connection(ctx.tenant_id,ctx.user_id)
        with connection.cursor() as q:
            q.execute('SELECT subscription_journey_required FROM companies WHERE tenant_id=%s',(ctx.tenant_id,))
            cohort=q.fetchone()
        connection.commit()
        if cohort is None or cohort[0] is not True:
            raise HTTPException(409,'Existing account retains its original billing journey')
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Journey temporarily unavailable') from None
    finally:
        if connection is not None:connection.close()
    try:
        with factory(ctx) as journey: yield journey
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Journey temporarily unavailable') from None


@router.post('/trial-journeys')
def start(choice: PlanChoice, request: Request, response: Response, ctx: TenantContext=Depends(get_tenant_context)):
    # Stable across lost responses, isolated by authenticated tenant AND actor.
    operation=uuid5(UUID(ctx.tenant_id),'recurring-journey:'+ctx.user_id+':'+str(choice.request_key))
    with _journey(request,response,ctx) as journey:
        return _invoke(lambda:journey.start(operation,choice.plan_key,choice.period_code))


@router.get('/trial-journeys/{operation_id}/progress')
def progress(operation_id: UUID, request: Request, response: Response, ctx: TenantContext=Depends(get_tenant_context)):
    with _journey(request,response,ctx) as journey:
        return _invoke(lambda:journey.progress(operation_id))


@router.post('/trial-journeys/{operation_id}/advance')
def advance(operation_id: UUID, choice: LanguageChoice, request: Request, response: Response,
            ctx: TenantContext=Depends(get_tenant_context)):
    with _journey(request,response,ctx) as journey:
        return _invoke(lambda:journey.advance(operation_id,choice.language))


@router.post('/trial-journeys/{operation_id}/cancellation')
def cancellation(operation_id: UUID, request: Request, response: Response, ctx: TenantContext=Depends(get_tenant_context)):
    with _journey(request,response,ctx) as journey:
        return _invoke(lambda:journey.cancel(operation_id))


@router.post('/trial-journeys/{operation_id}/cleanup')
def cleanup(operation_id: UUID, request: Request, response: Response, ctx: TenantContext=Depends(get_tenant_context)):
    with _journey(request,response,ctx) as journey:
        return _invoke(lambda:journey.cleanup(operation_id))
