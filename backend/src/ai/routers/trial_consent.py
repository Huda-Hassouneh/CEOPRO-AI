"""Default-off authenticated collection; no runtime writer/approval factory installed."""
import os
from contextlib import contextmanager
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr, StrictBool, Field
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.billing.authenticated_consent import CollectionBlocked, MISSING_APPROVALS
from src.ai.routers.trial_journey_preview import trial_journey_preview

router = APIRouter()


class PresentationChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['en', 'ar']


class AcceptanceChoice(PresentationChoice):
    presentation_id: UUID
    challenge: SecretStr = Field(min_length=72, max_length=72)
    checked: StrictBool


class WithdrawalChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    presentation_id: UUID


def _owned(request, response, operation, ctx):
    if os.getenv('RECURRING_CONSENT_ENABLED', '').strip().lower() != 'true':
        raise HTTPException(404, 'Consent unavailable')
    # Reuses B2a's exact authenticated read and default-off gate. No cookie auth,
    # client tenant GUC, policy identity, price or provider identity is accepted.
    preview = trial_journey_preview(operation, response, ctx)
    response.headers['Cache-Control'] = 'no-store'
    return preview


@contextmanager
def _flow(request, ctx):
    # No credential resolver or default factory. Approved composition must own
    # dedicated sockets through a context manager; nothing is put in app state here.
    factory = getattr(request.app.state, 'recurring_consent_factory', None)
    try:
        if factory is None:
            yield None
        else:
            with factory(ctx) as flow:
                yield flow
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Consent temporarily unavailable') from None


def _invoke(action):
    from src.ai.billing.recurring_consent import ConsentError
    try:
        return action()
    except CollectionBlocked as error:
        raise HTTPException(409, str(error)) from None
    except ConsentError as error:
        category = str(error)
        if category == 'consent_55000':
            raise HTTPException(409, 'post_confirmation_cancellation_or_fresh_status_required') from None
        code = 403 if category == 'consent_42501' else 409
        raise HTTPException(code, 'consent_boundary_refused') from None
    except Exception:
        raise HTTPException(503, 'Consent temporarily unavailable') from None


@router.get('/trial-journeys/{operation_id}/consent/preparation')
def prepare(operation_id: UUID, request: Request, response: Response, language: Literal['en','ar']='en',
            ctx: TenantContext = Depends(get_tenant_context)):
    preview = _owned(request, response, operation_id, ctx)
    with _flow(request, ctx) as flow:
        value = (_invoke(lambda: flow.prepare(operation_id, language)) if flow else
            dict(state='pending_policy', missing_approvals=list(MISSING_APPROVALS), blocker='policy_not_approved',
                 agreement_text=None, policy_revision=None))
    return dict(operation_id=str(operation_id), commercial_terms=preview.commercial_terms,
        provider_consent='unresolved_provider_requirement', **value)


@router.post('/trial-journeys/{operation_id}/consent/present')
def present(operation_id: UUID, choice: PresentationChoice, request: Request, response: Response,
            ctx: TenantContext = Depends(get_tenant_context)):
    _owned(request, response, operation_id, ctx)
    with _flow(request, ctx) as flow:
        if flow is None: raise HTTPException(409, 'policy_not_approved')
        return _invoke(lambda: flow.present(operation_id, choice.language))


@router.post('/trial-journeys/{operation_id}/consent/accept')
def accept(operation_id: UUID, choice: AcceptanceChoice, request: Request, response: Response,
           ctx: TenantContext = Depends(get_tenant_context)):
    _owned(request, response, operation_id, ctx)
    if choice.checked is not True: raise HTTPException(409, 'unchecked_consent')
    with _flow(request, ctx) as flow:
        if flow is None: raise HTTPException(409, 'policy_not_approved')
        return _invoke(lambda: flow.accept(operation_id, choice.language, choice.presentation_id,
            choice.challenge.get_secret_value(), choice.checked))


@router.post('/trial-journeys/{operation_id}/consent/withdraw')
def withdraw(operation_id: UUID, choice: WithdrawalChoice, request: Request, response: Response,
             ctx: TenantContext = Depends(get_tenant_context)):
    _owned(request, response, operation_id, ctx)
    with _flow(request, ctx) as flow:
        if flow is None: raise HTTPException(503, 'Protected consent service unavailable')
        return _invoke(lambda: flow.withdraw(operation_id, choice.presentation_id))
