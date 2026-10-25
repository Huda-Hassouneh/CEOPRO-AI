# Billing return origin and Checkout recovery

Set `PUBLIC_FRONTEND_ORIGIN` to this environment's trusted frontend origin. Use
HTTPS for public hosts; HTTP is accepted only for loopback development. Do not
include credentials, a path, query or fragment. `CORS_ALLOWED_ORIGINS` separately
lists the exact frontend origin that may call the API. The frontend's
`VITE_API_BASE_URL` points to the API, not the frontend or webhook listener.

When the public setting is absent, legacy `FRONTEND_BASE_URL`, `APP_BASE_URL` and
`FRONTEND_URL` must agree. There is no implicit payment/email return to port
5173. The configuration checker reports missing, unsafe or ambiguous settings.
Email links, authentication callbacks, Shopify callbacks, Checkout and Customer
Portal returns share `src.infrastructure.public_urls.frontend_origin`.

## Durable purchase protection

Migration `20261104000000_durable_fixed_plan_checkout.sql` adds tenant-isolated
Checkout reservations. It does not replace the subscription, quote, webhook or
credit authorities. A tenant lock serializes fixed and Custom purchase attempts.
An existing current subscription requires a supported plan change or recovery,
not another Checkout. Pre-existing provider subscriptions and open sessions are
reconciled before a new reservation is created.

The provider request and idempotency identity are frozen before session creation.
A retry uses those exact parameters; an existing open session is returned rather
than duplicated. A different purchase is refused while one is pending. Unknown
outcomes older than 23 hours require operator reconciliation before another
provider operation; do not clear reservations or create replacement purchases
merely to get past that refusal.

`POST /billing/checkout/cancel-pending` expires an open session and its reservation.
It does not cancel a completed payment. A completed return is confirmed only when
`GET /billing/checkout-status?session_id=...` finds the matching tenant, customer
and webhook-synchronized active/trialing subscription. Redirects grant no rights.
A verified terminal subscription permits a later resubscription reservation.

## Plan changes

`POST /billing/change-plan/preview` uses the same rights classification as the
mutation. The server revalidates at confirmation. Paid upgrades retain Stripe's
existing proration/pending-payment behavior; Stripe trials retain their trial end
without proration. Downgrades retain current rights until the period boundary.
The preview intentionally leaves an unknown immediate charge unset. It does not
invent a credit carryover, refund, replacement or production pricing policy.

## Reproducible browser evidence

Frontend `tests/browser/original-billing.mjs` exercises a real isolated API and
requires explicit synthetic credentials. Quote creation additionally requires
`E2E_QUOTE_APPROVED_ONCE=YES`, with a persistent intent/identity file preventing an
unreviewed retry. Existing quotes are retrieved on subsequent runs.

`original-billing-visual.mjs` reads the supplied original React frontend without
writing to it and compares original/integrated component screenshots using labeled
synthetic presentation data. It removes only the reference files it created.

`stripe-hosted-restoration.mjs` requires `KEEL_REAL_STRIPE_TEST=YES`, the approved
test ledger, the exact isolated origins, and a separate `E2E_ALLOW_TEST_PAYMENT=YES`
flag before submitting Stripe's synthetic test card. It observes the actual API
response without substituting fixture responses. Keep credentials, live Checkout
URLs, provider ledgers and generated evidence outside Git. Never use these tests
with a production tenant, database, account or live key.

## Verified Custom and promotion corrections

`20261104000100_owner_custom_pricing_rate_evidence.sql` exposes bound cost
evidence only through an active Platform Owner command. The runtime role still
has no direct SELECT privilege on private accounting provider-cost schedules.
Quote calculation continues to use the Python calculator and immutable snapshot
authority; customers cannot supply prices, margins or provider rates.

Paid Custom quote provisioning uses a closed allowance vector: selected numeric
limits retain their approved values and unpurchased capabilities receive no
allowance. This does not rewrite the immutable quote's omitted fields or change
the patch semantics of separately authorized administrative custom contracts.
Verified updates can fill missing overrides for the exact existing quote
contract; explicit owner overrides and newer contract references are preserved.

Managed Checkout sends its bound Stripe discount without the mutually exclusive
`allow_promotion_codes` field. A definite Stripe validation rejection releases
the failed attempt with audit evidence. Timeouts and unknown outcomes remain
quarantined. Immutable request parameters are never edited to force a retry.

`20261104000200_tenant_promotion_capacity_check.sql` lets authenticated validation
report exhausted campaign/tenant capacity without exposing cross-tenant
redemptions. Atomic reservation remains the final concurrency check.

`owner-billing-restoration.mjs` and `custom-paid-review.mjs` are read-only browser
checks using authorized synthetic logins. The original owner catalog remains
the default; its existing versioned policy/cost/review links preserve query
context inside that same owner shell. Paid offer history never implies that a
later cancelled subscription still has access.
