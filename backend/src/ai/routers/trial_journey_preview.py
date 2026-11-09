"""Disabled read-only B2a projection. A checkpoint is never consent or authority."""
from decimal import Decimal
import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context

router = APIRouter()


class CommercialPreview(BaseModel):
    plan_key: str
    renewal_amount: str
    currency: str
    interval_months: int
    trial_duration_days: int


class JourneyPreview(BaseModel):
    operation_id: UUID
    state: Literal['eligible', 'pending_verification', 'conflict', 'expired', 'blocked']
    reason: str
    commercial_terms: CommercialPreview | None = None


class _Checkpoint:
    """Capture the coordinator's single authorized read; no second snapshot."""
    def __init__(self, repository):
        self.repository, self.row, self.loaded = repository, None, False

    def load(self, operation_id):
        self.row = self.repository.load(operation_id)
        self.loaded = True
        return self.row


def _project(operation_id, result, row, ctx):
    r, checkout = row['reservation'], row['checkout']
    # Defense in depth: context is issued by get_tenant_context, never query JSON.
    if (r['attempt_id'] != str(operation_id) or checkout['attempt_id'] != str(operation_id)
            or r['tenant_id'] != ctx.tenant_id or checkout['tenant_id'] != ctx.tenant_id
            or r['started_by_user_id'] != ctx.user_id):
        raise HTTPException(404, 'Trial operation unavailable')
    state, reason = 'blocked', 'integration_required'
    if result.state.value == 'conflict':
        return JourneyPreview(operation_id=operation_id, state='conflict', reason='checkpoint_conflict')
    if checkout['state'] == 'expired':
        state, reason = 'expired', 'checkout_expired'
    elif r['state'] == 'pending' and result.state.value == 'consent_required':
        # Eligible for terms review only; no claim of consent or trial access.
        state, reason = 'eligible', 'reserved_terms_available'
    elif r['state'] == 'pending' and result.state.value == 'pending':
        state, reason = 'pending_verification', 'verification_incomplete'
    try:
        terms = r['approved_terms']
        for key in ('plan_key', 'currency', 'interval_months', 'trial_duration_days'):
            if terms[key] != r[key]:
                raise ValueError('Frozen terms conflict')
        amount, stored = terms['approved_amount'], r['approved_amount']
        # The strict socket decodes numeric JSON with Decimal, never binary float.
        if isinstance(amount, (float, bool)) or isinstance(stored, (float, bool)):
            raise ValueError('Exact amount required')
        amount = Decimal(amount)
        if not amount.is_finite() or amount < 0 or amount != Decimal(stored):
            raise ValueError('Frozen amount conflict')
        commercial = CommercialPreview(plan_key=terms['plan_key'], renewal_amount=str(amount),
            currency=terms['currency'], interval_months=terms['interval_months'],
            trial_duration_days=terms['trial_duration_days'])
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return JourneyPreview(operation_id=operation_id, state='conflict', reason='frozen_terms_unavailable')
    return JourneyPreview(operation_id=operation_id, state=state, reason=reason, commercial_terms=commercial)


@router.get('/trial-journeys/{operation_id}', response_model=JourneyPreview)
def trial_journey_preview(operation_id: UUID, response: Response,
                          ctx: TenantContext = Depends(get_tenant_context)):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Authorization'
    if os.getenv('RECURRING_JOURNEY_PREVIEW_ENABLED', '').strip().lower() != 'true':
        raise HTTPException(404, 'Trial operation unavailable')
    connection = None
    try:
        # This is the only permitted runtime coordinator consumer: read status,
        # with no Customer, consent, observer, sender or confirmation dependencies.
        from src.ai.billing.trial_coordinator import ReservationRepository, TrialCoordinator
        connection = db.billing_preview_connection(ctx.tenant_id, ctx.user_id)
        checkpoint = _Checkpoint(ReservationRepository(connection))
        result = TrialCoordinator(checkpoint).status(operation_id)
        if not checkpoint.loaded:
            raise HTTPException(503, 'Trial preview temporarily unavailable')
        if checkpoint.row is None:
            raise HTTPException(404, 'Trial operation unavailable')
        return _project(operation_id, result, checkpoint.row, ctx)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Trial preview temporarily unavailable') from None
    finally:
        if connection is not None:
            connection.close()
