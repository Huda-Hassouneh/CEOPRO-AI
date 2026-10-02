# Subscription & Billing Domain

## Purpose
Owns plans, subscriptions, checkout/change-plan flows, invoices, promo codes, custom plans/quotes, pricing policy/rates, onboarding, and payment-provider integration.

## Structure
- `index.ts` is the public domain router and also exports the Stripe webhook router.
- `route/`, `controller/`, `service/`, and `repo/` contain the existing layered billing logic.
- `client/payment-providers/` isolates Stripe/PayPal provider code.
- `types/` contains billing DTOs and provider/domain contracts.

## Important decisions
- Existing API paths and response contracts are unchanged.
- Stripe webhook routing remains mounted before `express.json()` so signature verification receives the raw request body.
- Stripe customer reuse remains tenant-aware.
- Checkout pricing remains server-authoritative.
- Accepted custom plans remain protected by the existing immutability/privacy rules.
- Monitoring frequency remains configuration of competitor management, not a standalone feature; tracked competitor count remains the capacity input.
- Custom-plan pricing continues to use configured vendor/infrastructure rates and quote snapshots/fingerprints.
- Promo-code and plan transition behavior is unchanged.
- Payment-provider implementation moved under `client/` without altering provider calls.

## Integrations
See `STRIPE_INTEGRATION.md` for the active payment-provider integration. There is no direct AI integration owned by this domain.
