# Stripe Integration

## Purpose
Documents the active payment-provider boundary for plans, checkout, customers, subscriptions, coupons, billing portal, schedules, test clocks, and webhooks.

## Code ownership
Provider API calls live under `client/payment-providers/stripe/`. Subscription business rules stay under `service/`; webhook event orchestration stays in `service/stripe-webhook.service.ts`; HTTP handling stays in `controller/` and `route/`.

## Critical webhook rule
`app.ts` mounts the Stripe webhook router at `/stripe/webhooks` before `express.json()`. The webhook route uses `express.raw({ type: "application/json" })`; do not move it behind the JSON parser or Stripe signature verification can break.

## Customer ownership
Existing customer reuse is tenant-aware when `tenantId` is available. Email alone must not establish tenant ownership.

## Server-authoritative billing
Plan prices, custom-plan decisions, promo-code behavior, transitions, and local persistence remain backend responsibilities. Stripe identifiers represent provider state; they do not replace CEOPRO tenant/plan authorization.

## Webhook processing
Webhook events are audited/idempotent through the existing webhook repository. Events are marked processed only after business handling succeeds so provider retries remain possible on failure.

## Configuration
The Stripe client obtains `STRIPE_SECRET_KEY` from required environment configuration. Existing network retry behavior remains unchanged.

## PayPal
A PayPal client placeholder remains under `client/payment-providers/paypal/`, but the current active billing flows in this codebase are Stripe-centric. Do not treat the placeholder as a production-complete PayPal integration without implementing and testing its contracts separately.
