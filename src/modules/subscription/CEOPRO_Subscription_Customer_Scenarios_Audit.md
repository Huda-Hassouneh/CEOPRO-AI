# CEOPRO Subscription Customer Scenarios — Current Behavior & Fix Audit

**Audit date:** 2026-10-02  
**Scope:** Customer-facing subscription lifecycle: standard plans, Stripe Checkout, trials, promo codes, recurring billing, failed payments, plan changes, cancellation, custom-plan checkout, webhook synchronization, and frontend confirmation/recovery UX.

## Code snapshots reviewed

- Backend: `backend(20261002-104736).zip`
- Frontend: `frontend(20260930-084004).zip` (latest frontend snapshot available in the project files used for this audit)
- Backend subscription docs and architecture notes included with the backend snapshot

> This document describes what the current code does. Where a behavior is unsafe, misleading, incomplete, or poor UX, it is called out again in **To Fix**.

---

# 1. Business mental model

The most important rule in the current implementation is:

> `POST /subscription/checkout` does **not** directly charge the customer. It validates the commercial request and creates a Stripe-hosted Checkout Session. Stripe handles the payment, and Stripe webhooks later synchronize the real subscription/payment outcome into CEOPRO.

The business flow is:

```text
Customer chooses plan
        ↓
CEOPRO validates plan, billing option, promo, permission, existing subscription
        ↓
CEOPRO creates/reuses Stripe Customer
        ↓
CEOPRO creates Stripe Checkout Session
        ↓
Customer completes payment/authentication on Stripe
        ↓
Stripe creates/updates subscription and invoice/payment state
        ↓
Stripe sends webhooks
        ↓
CEOPRO synchronizes local subscription + payment history + promo redemption
        ↓
Entitlement system decides whether features are accessible
```

Stripe is the payment source of truth. CEOPRO remains authoritative for tenant ownership, allowed plans, promo eligibility, feature entitlements, usage allocations, and application access.

---

# 2. Subscription statuses and customer access

The current backend maps Stripe statuses into CEOPRO statuses as follows:

| Stripe state | CEOPRO state | Access granted? | Business meaning |
|---|---|---:|---|
| `trialing` | `trialing` | Yes | Customer is inside a valid free trial. |
| `active` | `active` | Yes | Subscription is commercially active. |
| `past_due` | `past_due` | **No** | Renewal/payment is overdue but Stripe may still retry. |
| `incomplete` | `pending` | **No** | Initial subscription payment/authentication is incomplete. |
| `unpaid` | `payment_failed` | **No** | Stripe considers collection unsuccessful after recovery attempts. |
| `paused` | `paused` | **No** | Subscription exists but access is suspended. |
| `canceled` | `cancelled` | **No** | Subscription has ended. |
| `incomplete_expired` | `expired` | **No** | Initial incomplete subscription expired. |

The entitlement layer currently grants subscription-based access only for:

```text
active
trialing
```

This is deliberately strict. `past_due`, `pending`, `payment_failed`, and `paused` still count as **current subscriptions** for lifecycle management, but they do not grant product access.

**Business reason:** the system separates “a billing relationship still exists” from “the customer is currently entitled to paid product access.”

**UX note:** blocking access immediately at `past_due` is internally consistent but harsh. Stripe may still be attempting payment recovery. This requires an explicit business decision; see **To Fix**.

---

# 3. Before Checkout: request and eligibility scenarios

## 3.1 Customer is not authenticated

**Current behavior**

The subscription route requires authentication. The customer cannot create a checkout session.

**Expected customer outcome**

No payment flow starts.

**Business reason**

A subscription must be attached to a known CEOPRO user and tenant.

**Assessment:** Correct.

---

## 3.2 Customer has no valid tenant context / membership

**Current behavior**

`requireTenant` blocks the request.

**Expected customer outcome**

No checkout is created.

**Business reason**

Subscriptions belong to tenants, not just email addresses or individual browser sessions.

**Assessment:** Correct.

---

## 3.3 Customer does not have `manage_billing`

**Current behavior**

`POST /subscription/checkout` requires `manage_billing` (or equivalent all-access permission).

**Expected customer outcome**

Request is rejected with a permission error.

**Business reason**

A normal team member should not be able to create a paid company subscription without billing authority.

**Assessment:** Correct.

---

## 3.4 Invalid request body

Examples:

- malformed/non-UUID `planId`
- unsupported billing period
- unsupported `payment_method` value
- empty or oversized promo code
- unexpected extra fields because the DTO is strict

**Current behavior**

Request validation fails before business logic executes.

**Expected customer outcome**

No Stripe customer/session is created.

**Business reason**

Invalid commercial input should fail before any provider-side billing objects are created.

**Assessment:** Correct.

---

## 3.5 Plan does not exist

**Current behavior**

Backend returns `PLAN_NOT_FOUND` (`404`).

**Expected customer outcome**

Checkout does not start.

**Business reason**

The browser cannot subscribe to an arbitrary or deleted plan identifier.

**Assessment:** Correct.

---

## 3.6 Standard plan exists but is inactive

**Current behavior**

Initial checkout rejects the plan because checkout requires an active plan.

**Expected customer outcome**

No new subscription can be created on that plan.

**Business reason**

Deactivating a plan should stop new sales without rewriting historical subscriptions.

**Assessment:** Correct.

---

## 3.7 Customer submits another tenant's custom-plan ID

**Current behavior**

Backend verifies `plan.planType === "custom"` and checks `plan.tenantId`. A foreign custom plan is rejected with `PLAN_NOT_AVAILABLE`.

**Expected customer outcome**

Checkout is denied.

**Business reason**

Custom plans can contain private negotiated pricing and entitlements and must remain tenant-private.

**Assessment:** Correct and security-important.

---

## 3.8 Requested billing period is not offered by the plan

**Current behavior**

Backend returns `INVALID_BILLING_PERIOD`.

**Expected customer outcome**

No Checkout Session is created.

**Business reason**

The customer can only buy billing terms explicitly configured by the owner for that plan.

**Assessment:** Correct.

---

## 3.9 Billing option exists but has no Stripe Price ID

**Current behavior**

Backend returns `PAYMENT_PROVIDER_ERROR`.

**Expected customer outcome**

Checkout cannot continue.

**Business reason**

CEOPRO must not charge using a client-calculated amount. The configured Stripe Price is required to keep provider billing and CEOPRO catalog state aligned.

**Assessment:** Correct failure behavior, but owner/admin monitoring should surface this configuration problem.

---

## 3.10 Customer already has an `active` subscription

**Current behavior**

A second checkout is blocked with `SUBSCRIPTION_ALREADY_EXISTS`.

The customer is expected to use the **plan-change** flow rather than create another subscription.

**Business reason**

One tenant should not accidentally have two concurrent subscriptions billing for the same CEOPRO account.

**Assessment:** Correct.

---

## 3.11 Customer already has a `trialing` subscription

**Current behavior**

A second checkout is also blocked. Plan changes use the plan-change path.

**Business reason**

Changing plans during a trial should modify the existing subscription rather than create multiple trials/subscriptions.

**Assessment:** Correct.

---

## 3.12 Customer has `past_due`, `pending`, `payment_failed`, or `paused`

**Current behavior**

These statuses are included in `CURRENT_SUBSCRIPTION_STATUSES`, so a new checkout is blocked with `SUBSCRIPTION_ALREADY_EXISTS`.

They do not grant access.

**Business reason**

The Stripe billing relationship still exists and should normally be recovered rather than duplicated.

**Assessment:** The principle is correct, but the current product lacks a complete customer recovery UX. **Needs fix.**

---

## 3.13 Customer's old subscription is `cancelled` or `expired`

**Current behavior**

These statuses are not treated as current subscriptions. The tenant can start a new Checkout Session.

**Business reason**

A terminated historical subscription must not permanently block a returning customer from subscribing again.

**Assessment:** Correct.

---

# 4. Stripe customer creation scenarios

## 4.1 Existing Stripe Customer belongs to the same tenant

**Current behavior**

The Stripe client searches by email but reuses a customer only when tenant metadata matches the CEOPRO tenant. It refreshes metadata when reused.

**Business reason**

Reusing the correct Stripe Customer preserves payment/billing continuity while maintaining tenant isolation.

**Assessment:** Correct.

---

## 4.2 Same email is used by multiple tenants

**Current behavior**

The backend does not blindly reuse the first Stripe customer with that email. Tenant metadata is authoritative when tenant context exists.

**Business reason**

Email is not a safe tenant ownership key in a multi-tenant SaaS.

**Assessment:** Correct and security-important.

---

## 4.3 Stripe customer creation/retrieval fails

Examples:

- Stripe outage
- network timeout after configured retries
- invalid Stripe credentials
- provider API error

**Current behavior**

The Stripe client throws. `checkoutService` does not convert the exception into `PAYMENT_PROVIDER_ERROR`; it reaches the global error path, so the customer is likely to see a generic `500 INTERNAL_SERVER_ERROR` rather than a provider-specific `502`.

**Business reason for desired behavior**

A provider outage is different from an internal CEOPRO bug. The customer should receive a retryable billing/provider error, and operations should be able to distinguish it.

**Assessment:** **Needs fix.**

---

# 5. Stripe Checkout Session creation scenarios

## 5.1 Session created normally

**Current behavior**

Backend returns:

```json
{
  "success": true,
  "message": "Checkout session created successfully",
  "data": {
    "checkoutUrl": "https://checkout.stripe.com/..."
  }
}
```

Frontend redirects the browser to Stripe.

**Business reason**

CEOPRO does not collect raw card details. PCI-sensitive payment entry is delegated to Stripe-hosted Checkout.

**Assessment:** Correct.

---

## 5.2 Stripe creates a session but returns no URL

**Current behavior**

Backend throws `Stripe Checkout Session was created without a checkout URL.`

The frontend also independently protects against a missing `checkoutUrl`.

**Business reason**

The customer cannot safely continue without the provider redirect URL.

**Assessment:** Correct defensive check.

---

## 5.3 Customer chooses PayPal

**Current behavior**

Backend rejects it with `UNSUPPORTED_PAYMENT_PROVIDER` (`422`).

**Business reason**

PayPal is present in the API vocabulary but is not part of the active production payment integration.

**Assessment:** Correct, though the UI should not offer it as actionable if unsupported.

---

## 5.4 Customer chooses card / Stripe / Google Pay

**Current behavior**

The DTO accepts `card`, `stripe`, and `googlePay`, but checkout creation does not explicitly configure different Stripe payment methods based on this value. The value is effectively used only to reject PayPal. Stripe Checkout itself decides which eligible payment methods/wallets are shown.

**Business reason**

Hosted Checkout can expose card and supported wallets according to Stripe configuration/device eligibility.

**Assessment:** Functional, but the API contract is ambiguous. **Needs contract cleanup/clarification.**

---

## 5.5 Customer intentionally clicks Back/Cancel in Stripe Checkout

**Current behavior**

Stripe redirects to `FAILED_SUBSCRIPTION_URL`, which the backend documentation describes as the URL used when checkout is cancelled or cannot continue.

The frontend `PaymentFailedPage` displays the generic failed-payment result.

**Business reason**

No subscription should be granted because checkout was not completed.

**Assessment:** Billing outcome is correct, but **UX is misleading** because a deliberate cancellation is shown as “payment failed.” **Needs fix.**

---

## 5.6 Customer closes the browser before finishing payment

**Current behavior**

If payment was never completed, no active subscription is created locally. The customer can later retry when no current Stripe subscription remains/current state expires.

**Business reason**

Closing the browser is not proof of payment.

**Assessment:** Correct.

---

## 5.7 Customer closes the browser after payment succeeded but before returning to CEOPRO

**Current behavior**

The backend does not depend on the browser returning. Stripe webhooks still synchronize the subscription and payment state.

**Business reason**

A paid customer must not lose their subscription because a browser tab closed after provider payment.

**Assessment:** Correct and important.

---

## 5.8 Checkout Session expires

**Current behavior**

`checkout.session.expired` has no explicit handler. It falls into the generic “unhandled event” path, is audited, and is marked processed.

No access is granted.

**Business reason**

An expired unpaid checkout should not produce a subscription entitlement.

**Assessment:** Core billing outcome is safe. Explicit expiry handling would improve analytics/recovery. **To fix / enhancement.**

---

# 6. Initial payment scenarios — no trial

## 6.1 Customer has sufficient funds and payment succeeds

**Current behavior**

Typical path:

```text
Stripe payment succeeds
→ checkout/session + subscription events arrive
→ CEOPRO upserts local subscription
→ status becomes active
→ invoice.payment_succeeded stores successful payment transaction
→ invoice.paid can consume promo redemption
→ usage allocations are ensured
→ features are accessible
```

A positive-value payment is recorded with amount/currency and payment/invoice identifiers.

**Business reason**

The tenant paid successfully and should receive the plan they purchased.

**Assessment:** Correct.

---

## 6.2 Customer has insufficient funds

**Current behavior**

Stripe rejects the payment attempt. During hosted Checkout the customer normally sees the provider decline and can try another method. If Stripe emits `invoice.payment_failed`, CEOPRO:

1. ensures the local subscription exists;
2. retrieves the authoritative Stripe subscription status;
3. synchronizes that status (`pending`, `past_due`, etc. depending on Stripe lifecycle);
4. resolves the PaymentIntent where possible;
5. stores a failed `paymentTransaction` with the provider failure message/code;
6. does not grant entitlement access unless the eventual status becomes `active` or `trialing`.

**Business reason**

No successful collection means the customer should not receive paid access merely because a checkout was attempted.

**Assessment:** Backend accounting is good. Customer recovery UX is incomplete. **Needs fix.**

---

## 6.3 Card is declined for another reason

Examples include generic issuer decline, fraud/security block, restricted card, unsupported transaction, or provider decline code.

**Current behavior**

Same failed-payment path as insufficient funds. CEOPRO stores the PaymentIntent failure message/decline code when available.

**Business reason**

CEOPRO should preserve the provider's failure reason for support/diagnostics rather than inventing its own payment result.

**Assessment:** Backend is good; frontend does not meaningfully expose recovery/failure reason. **Needs UX improvement.**

---

## 6.4 Expired card

**Current behavior**

Stripe Checkout validates/declines the method. If the failure becomes an invoice payment failure, CEOPRO records it through the generic failed-payment path.

**Business reason**

The customer must provide a valid payment method before paid access is granted.

**Assessment:** Correct provider delegation; recovery UX still applies.

---

## 6.5 Incorrect CVC or other card-validation failure

**Current behavior**

Stripe handles the validation/decline. CEOPRO does not receive raw card data.

**Business reason**

Sensitive payment validation belongs to the payment provider.

**Assessment:** Correct.

---

## 6.6 3D Secure / SCA authentication is required

**Current behavior**

Stripe may emit `invoice.payment_action_required`. CEOPRO:

- ensures/synchronizes the subscription;
- resolves/logs the PaymentIntent;
- deliberately does **not** classify it as permanent payment failure.

The handler contains a comment to add customer notification, but no notification/recovery action is currently implemented.

**Business reason**

The customer has not necessarily failed payment; they need to complete an authentication step.

**Assessment:** Status treatment is correct. **Customer notification/recovery is missing and must be fixed.**

---

## 6.7 Customer completes required 3DS/SCA successfully

**Current behavior**

Stripe continues payment. When the invoice succeeds, CEOPRO records the payment, synchronizes to `active`, and grants access.

**Business reason**

Authentication completed and the payment is now valid.

**Assessment:** Correct.

---

## 6.8 Customer abandons/fails 3DS/SCA

**Current behavior**

Subscription remains in the Stripe state produced by the failed/incomplete payment lifecycle. CEOPRO does not grant access unless it becomes `active`/`trialing`.

**Business reason**

Payment authorization was not completed.

**Assessment:** Correct access rule; recovery UX missing.

---

## 6.9 Initial subscription becomes `incomplete`

**Current behavior**

Mapped locally to `pending`.

- It counts as a current subscription.
- It blocks a second checkout.
- It grants no access.

**Business reason**

The existing billing attempt still has a lifecycle and must not be duplicated, but the customer has not successfully paid.

**Assessment:** Data model is correct; needs a clear “finish payment/recover payment” UX.

---

## 6.10 Initial incomplete subscription expires

**Current behavior**

Stripe `incomplete_expired` maps to local `expired`.

`expired` is not a current status, so a later new checkout is allowed.

**Business reason**

Once the failed initial attempt is terminal, the customer should be free to start a fresh purchase.

**Assessment:** Correct.

---

# 7. Trial scenarios

## 7.1 Plan has a free trial

**Current behavior**

Stripe Checkout is created with `trial_period_days = plan.trialPeriodValue` when the value is positive.

The system also uses:

```text
payment_method_collection = always
```

so the customer is still asked for a payment method.

Subscription becomes `trialing` and CEOPRO grants access.

**Business reason**

The customer can evaluate the paid product while a payment method is already available for automatic conversion at trial end.

**Assessment:** Correct.

---

## 7.2 Customer has little/no available funds when starting a trial

**Current behavior**

No normal subscription charge is due immediately, so available balance is generally not tested as a full plan charge at trial start. If Stripe accepts the payment method, the customer can enter `trialing` and receive access.

**Business reason**

A free trial is free now; commercial collection happens when the trial ends.

**Assessment:** Correct.

---

## 7.3 Trial ends and payment succeeds

**Current behavior**

Stripe charges the configured plan price. CEOPRO receives successful invoice/subscription webhooks, records the payment, synchronizes `active`, and access continues.

**Business reason**

The customer converted successfully from trial to paid subscriber.

**Assessment:** Correct.

---

## 7.4 Trial ends and card has insufficient funds / is declined

**Current behavior**

The normal renewal/payment-failure lifecycle applies. CEOPRO synchronizes the provider state and does not grant access once the status is no longer `trialing`/`active`.

**Business reason**

The free trial has ended and the paid period was not successfully funded.

**Assessment:** Correct accounting; recovery UX and strict `past_due` policy require attention.

---

## 7.5 Payment method disappears before trial end

**Current behavior**

Checkout trial configuration uses:

```text
trial_settings.end_behavior.missing_payment_method = cancel
```

So Stripe cancels rather than silently continuing unpaid or pausing indefinitely.

**Business reason**

The tenant should not convert into a paid service without a valid collection method.

**Assessment:** Correct and clean.

---

## 7.6 Stripe sends `customer.subscription.trial_will_end`

**Current behavior**

CEOPRO synchronizes the subscription and logs the event. The code explicitly notes that email/dashboard notification could be added, but it is not implemented.

**Business reason for desired behavior**

Customers should receive advance notice before a free trial converts into a paid charge.

**Assessment:** **Needs fix: customer notification missing.**

---

# 8. Promo-code scenarios

## 8.1 No promo code

**Current behavior**

Normal plan price is used through the configured Stripe Price.

**Assessment:** Correct.

---

## 8.2 Valid promo applicable to selected plan

**Current behavior**

Backend validates promo eligibility and sends the stored Stripe Coupon ID into Checkout.

The browser does not control the authoritative discount amount.

**Business reason**

The backend remains authoritative for discount eligibility while Stripe applies the actual provider-side discount.

**Assessment:** Correct.

---

## 8.3 Promo does not exist

**Current behavior**

`PROMO_CODE_NOT_FOUND`.

**Business reason**

Unknown discounts must not alter price.

**Assessment:** Correct.

---

## 8.4 Promo is inactive or has not started yet

**Current behavior**

`PROMO_CODE_NOT_ACTIVE`.

**Business reason**

Campaign time windows must be enforced server-side.

**Assessment:** Correct.

---

## 8.5 Promo has expired

**Current behavior**

`PROMO_CODE_EXPIRED`.

**Assessment:** Correct.

---

## 8.6 Global promo usage limit reached

**Current behavior**

`PROMO_CODE_USAGE_LIMIT_REACHED`.

**Business reason**

A limited campaign must not exceed the configured commercial exposure.

**Assessment:** Correct.

---

## 8.7 Tenant/user redemption limit reached

**Current behavior**

The same `PROMO_CODE_USAGE_LIMIT_REACHED` result is returned.

**Business reason**

A tenant cannot repeatedly redeem a one-customer promotion beyond its configured allowance.

**Assessment:** Correct.

---

## 8.8 Promo is not linked/applicable to the selected plan

**Current behavior**

`PROMO_CODE_NOT_APPLICABLE`.

**Assessment:** Correct.

---

## 8.9 Fixed-amount coupon currency does not match plan currency

**Current behavior**

The system prevents linking a fixed-amount Stripe coupon to a plan with a different currency and returns `PROMO_CODE_CURRENCY_MISMATCH`.

**Business reason**

A fixed amount cannot be safely interpreted across currencies without an explicit conversion rule.

**Assessment:** Correct.

---

## 8.10 Promo gives 100% off / invoice settles for zero

**Current behavior**

A zero-value successful invoice is **not** recorded as a monetary payment transaction.

However, `invoice.paid` still consumes the promo redemption for the initial subscription invoice.

**Business reason**

A $0/JOD0 invoice is a valid subscription settlement but not a real cash payment. The promotion still counts as used.

**Assessment:** Correct.

---

## 8.11 Partial promo and remaining amount succeeds

**Current behavior**

Successful transaction records the actual amount Stripe reports as paid.

**Business reason**

Revenue history should reflect money actually collected, not undiscounted catalog price.

**Assessment:** Correct.

---

## 8.12 Partial promo and remaining amount fails

**Current behavior**

Normal payment-failure lifecycle applies. Promo redemption is tied to invoice settlement, so a failed unpaid invoice is not treated as a successful redemption settlement.

**Assessment:** Correct.

---

# 9. Webhook ordering, retries, and synchronization scenarios

## 9.1 `customer.subscription.created` arrives before `checkout.session.completed`

**Current behavior**

The code supports this ordering. If tenant metadata is available on the subscription, it synchronizes immediately. If tenant identity is unavailable, the handler waits for a later event such as checkout completion.

`checkout.session.completed` retrieves the authoritative Stripe subscription and upserts it locally.

**Business reason**

Stripe does not guarantee webhook ordering. Customer access cannot depend on one exact event sequence.

**Assessment:** Correct.

---

## 9.2 `checkout.session.completed` arrives before subscription-created processing

**Current behavior**

Checkout completion retrieves and synchronizes the Stripe subscription. Later subscription events are safe because local subscription persistence uses upsert/idempotent synchronization.

**Assessment:** Correct.

---

## 9.3 Invoice event arrives before the local subscription exists

**Current behavior**

Invoice handlers call `ensureLocalSubscriptionForInvoice()`, retrieve the Stripe subscription if needed, resolve tenant metadata, and create/synchronize the local subscription.

**Business reason**

Payment accounting must not fail merely because another Stripe event arrived later.

**Assessment:** Correct.

---

## 9.4 Same Stripe webhook is delivered more than once

**Current behavior**

Webhook events are stored using provider event ID and duplicate processed events return:

```json
{
  "received": true,
  "duplicate": true
}
```

Subscription writes are upserts. Payment transactions are idempotent by invoice. Promo redemption is unique by promo + subscription and runs transactionally.

**Business reason**

Stripe retries webhooks, and repeated delivery must not create duplicate subscriptions, revenue transactions, or promo usage.

**Assessment:** Correct and production-important.

---

## 9.5 Webhook processing fails due to temporary DB/provider problem

**Current behavior**

The event is **not** marked processed. Controller returns a non-2xx (`500`), causing Stripe to retry.

**Business reason**

Temporary internal failure should not permanently lose a paid customer's billing event.

**Assessment:** Correct.

---

## 9.6 Invalid/missing Stripe webhook signature

**Current behavior**

Rejected before business processing with `INVALID_WEBHOOK_HEADER` / `400`.

**Business reason**

An attacker must not be able to fake “payment succeeded” events.

**Assessment:** Correct and security-critical.

---

## 9.7 `checkout.session.completed` contains no subscription ID

**Current behavior**

Handler logs a warning and returns normally. The webhook is then marked processed.

**Business reason for desired behavior**

In subscription-mode Checkout this is an abnormal reconciliation state. Silently treating it as fully processed may hide a paid/checkout inconsistency.

**Assessment:** **Needs stronger handling/monitoring.**

---

## 9.8 Browser returns before webhook has created the local subscription

**Current frontend behavior**

`PaymentSuccessPage` runs `useSubscriptionConfirmation()`, which polls `GET /subscription/current` up to 6 times at roughly 1.5-second intervals.

If no local subscription appears, it shows a pending state and allows retry.

**Business reason**

Provider payment and application synchronization are asynchronous; the customer should not see an immediate false failure because the webhook is a few seconds behind.

**Assessment:** Good pattern, but the confirmation condition itself is too weak; see next scenario.

---

## 9.9 Local subscription exists, but status is `pending`, `past_due`, `payment_failed`, or `paused`

**Current frontend behavior**

The confirmation hook currently does:

```text
if a subscription object exists → confirmed
```

It does **not** require `status === active || status === trialing`.

Therefore the success page can theoretically display “confirmed” for a non-access-granting subscription state.

**Business reason for desired behavior**

“Subscription record exists” and “customer successfully subscribed” are not the same business condition.

**Assessment:** **Incorrect success UX — must fix.**

---

# 10. Renewal scenarios

## 10.1 Recurring renewal succeeds

**Current behavior**

`invoice.payment_succeeded`:

- synchronizes subscription;
- records payment transaction as `succeeded` when `amount_paid > 0`;
- classifies subscription-cycle payments as recurring;
- access remains active;
- usage allocations are ensured for the synchronized active period.

**Business reason**

A successfully renewed customer should continue without interruption and the business should capture recurring revenue history.

**Assessment:** Correct.

---

## 10.2 Renewal invoice is zero-value

Examples:

- 100% discount
- credit balance
- another provider-side zero settlement

**Current behavior**

Subscription is synchronized, but no fake monetary transaction is stored for amount zero.

**Business reason**

“Invoice settled” is not always “cash collected.”

**Assessment:** Correct.

---

## 10.3 Renewal fails due to insufficient funds / decline

**Current behavior**

Typical path:

```text
active
→ renewal attempt fails
→ invoice.payment_failed
→ CEOPRO records failed payment + reason
→ CEOPRO reads Stripe's current subscription state
→ commonly becomes past_due
→ past_due grants no CEOPRO entitlement access
→ Stripe may retry according to Stripe billing settings
```

**Business reason**

The system follows Stripe as the collection source of truth.

**Assessment:** Technically consistent. Immediate access loss at `past_due` is a business/UX decision that should be reviewed.

---

## 10.4 Stripe retries the same failed renewal and later succeeds

**Current behavior**

The payment transaction uses an invoice-based idempotency key. A later success for the same invoice upserts the transaction from failed to succeeded, clears the failure reason, synchronizes the subscription back to its successful provider state, and access can be restored.

**Business reason**

One invoice should converge to its final collection outcome rather than creating contradictory duplicate records.

**Assessment:** Correct.

---

## 10.5 Stripe eventually marks the subscription `unpaid`

**Current behavior**

Mapped to `payment_failed`. It remains a current subscription and grants no access.

**Business reason**

Payment recovery failed, but the provider billing object still exists and should be managed rather than duplicated.

**Assessment:** Correct model; recovery/cancellation path must be obvious to the customer.

---

## 10.6 Renewal requires 3DS/SCA

**Current behavior**

`invoice.payment_action_required` synchronizes state and logs the PaymentIntent, but no customer-facing notification/action is triggered by CEOPRO.

**Business reason for desired behavior**

The customer must know that action is required or the subscription can become delinquent even though funds/card are otherwise valid.

**Assessment:** **Needs fix.**

---

## 10.7 Invoice cannot be finalized

**Current behavior**

`invoice.finalization_failed` synchronizes the connected subscription when present and logs the provider finalization error. It correctly does **not** record this as a card/payment failure because collection may never have been attempted.

No customer/admin workflow is implemented beyond logging.

**Business reason**

Invoice generation problems are operational/billing configuration problems, not necessarily customer payment problems.

**Assessment:** Classification is correct. **Alert/recovery path is missing.**

---

## 10.8 Invoice is marked paid out-of-band

**Current behavior**

`invoice.paid` synchronizes subscription and promo settlement logic but does not blindly create a monetary transaction.

**Business reason**

`invoice.paid` does not always mean Stripe collected money electronically.

**Assessment:** Correct.

---

# 11. Failed-payment recovery scenarios

## 11.1 Customer is `past_due` and tries to start a new subscription

**Current behavior**

New checkout is blocked because `past_due` is a current subscription.

**Desired business behavior**

Customer should recover the existing subscription by updating/confirming payment, not create a duplicate.

**Current gap**

There is no complete customer-facing payment-recovery/payment-method-update flow in the reviewed subscription UI/API.

**Assessment:** **Needs fix.**

---

## 11.2 Customer is `payment_failed` and tries a new checkout

**Current behavior**

Also blocked as an existing current subscription.

**Business reason**

Avoid duplicate subscriptions.

**Assessment:** Correct guard, incomplete recovery UX. **Needs fix.**

---

## 11.3 Customer is `paused`

**Current behavior**

No access, but still counted as current, so new checkout is blocked.

**Business reason**

The existing provider subscription should be resumed/recovered or intentionally terminated before replacing it.

**Assessment:** Requires a visible recovery/resume strategy. **Needs UX/product decision.**

---

## 11.4 Customer is `pending` after an incomplete initial payment

**Current behavior**

No access and no second checkout.

**Business reason**

Prevent duplicate subscriptions while the original payment attempt is still recoverable.

**Assessment:** Correct model but the customer needs a “complete payment” path rather than a dead end.

---

## 11.5 Failed-payment reason exists in backend transaction history

**Current behavior**

Backend stores Stripe failure reason/code in `paymentTransaction.failureReason`.

The reviewed frontend does not provide a rich recovery UI based on that reason; `PaymentFailedBanner` is only a hardcoded “Payment failed”.

**Business reason for desired behavior**

Useful customer messaging such as “card declined”, “authentication required”, or “update payment method” reduces support load and abandoned subscriptions.

**Assessment:** **Needs frontend/API surfacing improvement.**

---

# 12. Plan-change scenarios for an existing subscription

Plan change uses entitlement comparison, not only price.

General rule:

```text
Any entitlement loss → schedule at period end
Only entitlement gains → can apply immediately
```

This protects already-paid access.

## 12.1 Customer selects the exact same plan and billing period

**Current behavior**

`ALREADY_ACTIVE_PLAN`.

**Business reason**

There is nothing to change and no reason to create billing noise.

**Assessment:** Correct.

---

## 12.2 Same current plan is selected while a downgrade is already scheduled

**Current behavior**

Backend returns `CANCEL_DOWNGRADE_REQUIRED` and says the customer should cancel the pending downgrade to remain on the current plan.

**Problem**

No dedicated reviewed endpoint/UI action exists to cancel/release only the scheduled plan change.

**Assessment:** **Backend tells the customer to perform an action the product does not expose. Must fix.**

---

## 12.3 Customer requests the exact transition already scheduled

**Current behavior**

`ALREADY_SCHEDULED_PLAN`.

**Business reason**

Avoid duplicate/contradictory schedule changes.

**Assessment:** Correct.

---

## 12.4 Target standard plan is inactive

**Current behavior**

Plan change is rejected with `PLAN_NOT_AVAILABLE`.

**Business reason**

Customers should not move into a plan that is no longer sold.

**Assessment:** Correct.

---

## 12.5 Target custom plan belongs to another tenant

**Current behavior**

Rejected with `PLAN_NOT_AVAILABLE`.

**Assessment:** Correct.

---

## 12.6 Active paid customer upgrades to a plan with only entitlement gains

**Current behavior**

The change is immediate. Stripe updates the subscription with:

```text
proration_behavior = always_invoice
payment_behavior = pending_if_incomplete
```

The intended business behavior is:

- credit unused value from the current paid period;
- charge the prorated upgrade amount;
- grant the upgraded plan immediately after successful provider processing.

**Important current issue**

`changePlanService` returns a success message saying the applicable prorated amount **has been charged** as soon as the Stripe subscription update call returns. It does not inspect a pending update/payment outcome before claiming charge success.

With `pending_if_incomplete`, additional payment/authentication can still be unresolved.

**Assessment:** **Potentially misleading/incorrect success response — must fix.**

---

## 12.7 Paid upgrade's proration payment requires 3DS or fails

**Current behavior**

Stripe/provider webhooks can later report payment action/failure. However, the synchronous plan-change response can already have reported upgrade success/charged wording.

**Business reason for desired behavior**

Do not tell a customer “charged successfully” before the provider confirms the charge and transition.

**Assessment:** **Needs backend + frontend state handling.**

---

## 12.8 Customer upgrades during a free trial

**Current behavior**

For an immediate trialing change:

- target plan takes effect immediately;
- original trial end is preserved;
- no proration is generated;
- no charge occurs now;
- changing plans does not grant a fresh trial;
- full new-plan price is charged when the original trial ends.

**Business reason**

Customers should be able to evaluate a higher plan without losing or resetting the original trial, while preventing trial abuse.

**Assessment:** Correct.

---

## 12.9 Customer downgrades / target removes or reduces any entitlement

**Current behavior**

Change is scheduled for period end through a Stripe Subscription Schedule.

Until then:

- current plan remains active;
- `planId` remains current;
- `scheduledPlanId`/`scheduledBillingPeriod` represent the future target;
- customer keeps what they already paid for.

**Business reason**

Do not remove paid entitlements before the paid term finishes.

**Assessment:** Correct.

---

## 12.10 Target plan has both gains and losses (`mixed`)

**Current behavior**

Because at least one entitlement is lost/reduced, the whole transition is scheduled for period end.

**Business reason**

Protect the customer's existing paid entitlement package; do not partially strip access mid-term.

**Assessment:** Correct.

---

## 12.11 Equivalent entitlements but billing cycle changes

**Current behavior**

The transition is classified `equivalent`; compatibility logic then determines whether the commercial/billing-duration move is immediate or period-end.

**Business reason**

When product access is equivalent, the remaining concern is how the billing term changes financially.

**Assessment:** Reasonable, but frontend should show the effective timing returned by the backend rather than assuming “upgrade/downgrade” from price alone.

---

## 12.12 Customer is `past_due`, `payment_failed`, `paused`, or `pending` and tries to change plan

**Current behavior**

`changePlanService` uses `getActiveSubscriptionByTenant`, which recognizes only `active`/`trialing`. Therefore the change operation returns `SUBSCRIPTION_NOT_FOUND` for delinquent/current-but-not-access-granting states.

Meanwhile the frontend Billing Checkout page currently treats **any returned current subscription object** as `hasActiveSubscription = true` and attempts the plan-change API.

**Business reason for desired behavior**

A delinquent customer should be directed to payment recovery first, not told that their subscription is missing.

**Assessment:** **Frontend/backend UX mismatch — must fix.**

---

# 13. Cancellation scenarios

## 13.1 Active customer cancels

**Current behavior**

Cancellation is scheduled at the end of the current billing period (`cancel_at_period_end = true`). CEOPRO does not immediately delete local access.

Webhook synchronization later updates local cancellation state.

**Business reason**

The customer has already paid for the current term and should retain access until that term ends.

**Assessment:** Correct.

---

## 13.2 Trialing customer cancels

**Current behavior**

The trialing subscription is considered current and can be scheduled for cancellation.

**Business reason**

A trial customer must be able to prevent conversion to paid billing.

**Assessment:** Correct.

---

## 13.3 `past_due` customer cancels

**Current behavior**

The current-subscription lookup includes `past_due`, so the customer can still schedule cancellation on the actual Stripe subscription.

**Business reason**

Delinquency should not trap the customer in an unmanageable billing relationship.

**Assessment:** Correct.

---

## 13.4 Customer has no current subscription

**Current behavior**

`SUBSCRIPTION_NOT_FOUND`.

**Assessment:** Correct.

---

## 13.5 Current row has no provider subscription ID

**Current behavior**

`PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND`.

**Business reason**

CEOPRO must not pretend a Stripe cancellation happened if it cannot identify the provider subscription.

**Assessment:** Correct defensive behavior; this should trigger operational investigation.

---

## 13.6 Cancellation is already scheduled

**Current behavior**

`SUBSCRIPTION_ALREADY_CANCELED`.

**Business reason**

Avoid duplicate provider changes and make the current future state explicit.

**Assessment:** Correct.

---

## 13.7 Customer undoes a scheduled cancellation

**Current behavior**

If `cancelAtPeriodEnd` is true, backend asks Stripe to set it back to false. Webhook synchronizes local state.

**Business reason**

Customer can change their mind before the subscription ends.

**Assessment:** Correct.

---

## 13.8 Customer tries to undo cancellation when no cancellation is scheduled

**Current behavior**

`SUBSCRIPTION_NOT_CANCELED`.

**Assessment:** Correct.

---

## 13.9 A future plan change was scheduled, then customer cancels subscription

**Current behavior**

Stripe client first releases the existing Subscription Schedule and then makes cancellation the authoritative future action.

The pending downgrade/change is discarded.

**Business reason**

A subscription cannot cleanly have two conflicting future instructions: “move to another plan” and “end subscription.” Cancellation takes precedence.

**Assessment:** Correct.

---

## 13.10 Customer undoes cancellation after the previous plan schedule was released

**Current behavior**

Undoing cancellation restores the subscription, but the old released plan-change schedule is not automatically recreated.

**Business reason**

The earlier scheduled change was intentionally superseded by cancellation. Restoring the subscription should not silently recreate an old commercial decision.

**Assessment:** Correct, but UI should make this clear.

---

## 13.11 Subscription reaches actual end and Stripe deletes/cancels it

**Current behavior**

`customer.subscription.deleted` synchronizes the terminal status and clears scheduled plan fields.

Access is no longer granted.

**Business reason**

Once the paid lifecycle ends, future plan schedules are meaningless and premium access must stop.

**Assessment:** Correct.

---

# 14. Custom-plan subscription scenarios

Custom plans ultimately reuse the same Stripe subscription/payment lifecycle. The extra scenarios happen **before** payment.

## 14.1 Customer configuration is eligible for instant checkout

**Current behavior**

Backend recalculates price authoritatively at checkout time, creates/reuses an automatic quote, accepts/converts it to a tenant-private plan if needed, and then:

- if customer has no current subscription → creates normal Stripe Checkout;
- if customer has a current subscription → routes into plan-change logic.

**Business reason**

The customer can self-serve only when the request stays inside owner-defined safe pricing/review limits.

**Assessment:** Correct architecture.

---

## 14.2 Customer changes browser-supplied configuration/price after preview

**Current behavior**

Checkout recalculates server-side and does not trust a browser monetary value. Automatic quote reuse is protected using configuration/pricing fingerprints.

**Business reason**

The client must not be able to tamper with custom-plan price or assumptions.

**Assessment:** Correct and security-important.

---

## 14.3 Custom configuration requires manual review

**Current behavior**

Checkout returns a successful business response with:

```text
manualReviewRequired = true
quoteId
previewPrice
reasons
```

No Stripe checkout URL is issued yet.

**Business reason**

Risky/high-cost/out-of-policy configurations require owner review before CEOPRO commits to a price.

**Assessment:** Correct.

---

## 14.4 Customer manually submits a configuration that actually qualifies for instant processing

**Current behavior**

Manual-review endpoint rejects it with validation messaging explaining manual review is not required.

**Business reason**

Do not create unnecessary operational review work for requests that can be safely priced automatically.

**Assessment:** Correct.

---

## 14.5 Manual quote is expired before acceptance

**Current behavior**

Quote is marked/treated as expired and cannot be accepted.

**Business reason**

Pricing inputs, vendor rates, and FX assumptions can become stale. A commercial offer should not remain valid indefinitely.

**Assessment:** Correct.

---

## 14.6 Quote is already accepted

**Current behavior**

Acceptance is idempotent; if it already produced a plan, the existing plan is returned.

**Business reason**

Repeated clicks/retries should not create duplicate custom plans.

**Assessment:** Correct.

---

## 14.7 Customer already has an active/trialing subscription and buys an instant custom plan

**Current behavior**

The system performs a plan change rather than creating a second subscription. Entitlement gain/loss logic decides immediate vs period-end timing.

**Business reason**

One tenant should maintain one billing lifecycle while moving into its negotiated/custom entitlement package.

**Assessment:** Correct.

---

## 14.8 Customer has a delinquent current subscription and attempts custom-plan instant checkout

**Current behavior**

Custom checkout sees that a current subscription exists, then calls `changePlanService`. `changePlanService` only recognizes active/trialing subscriptions and can return `SUBSCRIPTION_NOT_FOUND`.

**Business reason for desired behavior**

The customer should first recover or terminate the delinquent billing lifecycle, not receive a misleading “subscription not found.”

**Assessment:** **Needs fix.**

---

# 15. Provider/API/system failure scenarios

## 15.1 Stripe is temporarily unavailable during normal checkout creation

**Current behavior**

Stripe client retries network failures a small number of times (`maxNetworkRetries: 2`). If it still fails, checkout throws and generally becomes an internal server error in the current standard checkout path.

**Desired behavior**

Return a provider-specific retryable error, keep the customer on the checkout review page, and allow retry without creating duplicate subscriptions.

**Assessment:** **Needs error-mapping fix.**

---

## 15.2 Stripe is unavailable during plan change

**Current behavior**

`changePlanService` catches the provider error and returns `PAYMENT_PROVIDER_ERROR`.

**Business reason**

The current plan should remain authoritative until the provider confirms the change.

**Assessment:** Better than the initial checkout error mapping.

---

## 15.3 Database fails while processing a webhook

**Current behavior**

Webhook processing returns failure and the event is not marked processed. Stripe receives non-2xx and can retry.

**Assessment:** Correct.

---

## 15.4 Provider sends an event CEOPRO does not explicitly support

**Current behavior**

Event is audited/logged as unhandled and marked processed.

**Business reason**

Unknown/unneeded events should not break the webhook endpoint.

**Assessment:** Correct for genuinely irrelevant events. Events that represent business states CEOPRO cares about should be explicitly handled.

---

# 16. Frontend page-state scenarios

## 16.1 Checkout page finds no current subscription

**Current behavior**

It uses the normal create-checkout path and allows promo entry.

**Assessment:** Correct.

---

## 16.2 Checkout page finds any current subscription object

**Current behavior**

Frontend sets:

```text
hasActiveSubscription = Boolean(subscription)
```

This includes `past_due`, `pending`, `payment_failed`, and `paused`, not just `active`/`trialing`.

It then attempts `changePlan`.

**Problem**

Backend plan change only recognizes `active`/`trialing`, so delinquent customers can hit confusing `SUBSCRIPTION_NOT_FOUND` behavior.

**Assessment:** **Must fix frontend status logic.**

---

## 16.3 Success return page sees active/trialing subscription

**Current behavior**

Polling finds a subscription and shows confirmed.

**Business outcome**

Correct.

---

## 16.4 Success return page sees a non-access subscription

**Current behavior**

Still shows confirmed because it checks existence only.

**Assessment:** **Incorrect. Must fix.**

---

## 16.5 Success return page cannot find subscription after polling window

**Current behavior**

Shows `pending` and offers “check again.”

**Business reason**

Webhook synchronization may be delayed.

**Assessment:** Good.

---

## 16.6 Backend returns a non-404 error during confirmation

**Current behavior**

Frontend shows an error state instead of pretending subscription succeeded.

**Assessment:** Correct.

---

## 16.7 Customer intentionally cancels hosted checkout

**Current behavior**

They can land on the generic Payment Failed page.

**Assessment:** Misleading UX. **Needs separate cancelled state/page.**

---

# 17. To Fix

This section contains behaviors that are either incorrect, misleading, incomplete, or likely to create poor customer/support UX.

## P0 — Fix before production payment traffic

### 1. Frontend success confirmation must validate subscription status

**Current:** any returned subscription object becomes `confirmed`.

**Fix:** only treat the purchase as confirmed when the returned state is commercially valid, at minimum:

```text
active
trialing
```

For other states:

- `pending` → show “payment still being completed” / recovery state;
- `past_due` → show payment issue/recovery state;
- `payment_failed` → show payment recovery state;
- `paused` → show suspended state.

**Why:** a DB row existing is not proof that the customer successfully paid or has access.

**Owner:** Frontend, with backend status contract unchanged.

---

### 2. Add a real payment-recovery flow for `past_due`, `payment_failed`, `pending`, and possibly `paused`

**Current:**

- new checkout is correctly blocked to avoid duplicate subscriptions;
- access is blocked for these statuses;
- there is no complete customer-facing path to update/confirm payment and recover the existing Stripe subscription.

**Fix options:**

- Stripe Customer Portal for payment-method/invoice recovery; or
- dedicated backend endpoints that create the appropriate Stripe recovery/payment flow.

Frontend should display a clear CTA such as **Update payment method / Complete payment / Resolve billing issue**.

**Why:** without this, customers can be trapped between “you already have a subscription” and “you do not have access.”

**Owner:** Backend + Frontend.

---

### 3. Billing Checkout must not treat every current subscription as active

**Current:**

```text
hasActiveSubscription = Boolean(subscription)
```

**Fix:** branch by actual status.

Suggested business routing:

```text
active/trialing → plan-change flow
past_due/payment_failed/pending → payment-recovery flow
paused → resume/recovery flow or support path
cancelled/expired/no subscription → new checkout
```

**Why:** the backend and frontend currently disagree about what “active subscription” means.

**Owner:** Frontend.

---

### 4. Do not claim a paid upgrade's proration “has been charged” until payment is confirmed

**Current:** paid immediate upgrade uses Stripe `pending_if_incomplete`, but service response can immediately say:

> “The applicable prorated amount has been charged.”

That can be false if authentication/payment is still incomplete.

**Fix:** inspect provider result/pending update and return one of explicit states, for example:

```text
applied
payment_action_required
payment_pending
scheduled
failed
```

Then let webhooks finalize the authoritative state.

**Why:** payment success messaging must reflect actual collection, especially for SCA/3DS and declines.

**Owner:** Backend + Frontend.

---

### 5. Expose a dedicated “cancel scheduled plan change” operation

**Current:** backend can return `CANCEL_DOWNGRADE_REQUIRED` saying the customer must cancel the pending downgrade, but no dedicated customer endpoint/action was found to release only that schedule.

**Fix:** add an explicit action such as:

```text
DELETE/PATCH /subscription/current/plan/scheduled
```

which releases the Stripe Subscription Schedule and clears local scheduled plan fields after provider confirmation/synchronization.

**Why:** the product must never instruct a customer to perform an action that is unavailable.

**Owner:** Backend + Frontend.

---

## P1 — Important billing UX/reliability fixes

### 6. Add customer handling for `invoice.payment_action_required`

**Current:** backend only logs.

**Fix:** notify customer and give them a path to complete authentication/payment.

**Why:** SCA is recoverable, not a permanent failure. Silence can unnecessarily turn valid subscribers delinquent.

**Owner:** Backend + Frontend/notifications.

---

### 7. Notify customers before trial ends

**Current:** `customer.subscription.trial_will_end` only logs.

**Fix:** email/in-app notification with trial end date, target plan/price, and payment method/recovery CTA where appropriate.

**Why:** reduces surprise charges, disputes, and involuntary churn.

**Owner:** Backend + notification system + Frontend optional.

---

### 8. Separate “checkout cancelled” from “payment failed”

**Current:** Stripe cancel URL uses `FAILED_SUBSCRIPTION_URL`, and the frontend `PaymentFailedPage` represents it as failure.

**Fix:** provide a separate cancelled/abandoned state, e.g.:

```text
/payment-cancelled
```

or include an explicit reason/state in the return route.

**Why:** a customer who intentionally pressed Back did not experience a card failure.

**Owner:** Backend environment/config + Frontend.

---

### 9. Map Stripe checkout creation failures to `PAYMENT_PROVIDER_ERROR`

**Current:** standard checkout provider exceptions can become generic `500 INTERNAL_SERVER_ERROR`.

**Fix:** catch Stripe customer/session creation errors in the subscription service and return the provider error contract (`502 PAYMENT_PROVIDER_ERROR`) while logging the detailed server-side cause.

**Why:** provider outages should be distinguishable from CEOPRO application bugs and presented as retryable billing failures.

**Owner:** Backend.

---

### 10. Surface useful failed-payment reason without exposing unsafe provider internals

**Current:** backend stores `failureReason`; frontend mainly shows generic “Payment failed.”

**Fix:** expose a normalized customer-safe reason/action such as:

```text
insufficient_funds
card_declined
expired_card
authentication_required
payment_method_missing
unknown
```

and display a useful next step.

**Why:** actionable failure messages reduce support tickets and improve recovery conversion.

**Owner:** Backend + Frontend.

---

### 11. Decide the business policy for `past_due` access

**Current:** access is removed immediately because only `active`/`trialing` grant access.

**Possible policies:**

- **Strict:** current behavior; access stops immediately on `past_due`.
- **Grace period:** continue limited/full access for a defined time while Stripe retries, then block.
- **Feature-specific grace:** allow read-only/core access while blocking cost-heavy features.

**Why:** Stripe may be actively recovering a renewal. Immediate lockout can cause avoidable churn, but allowing unpaid usage has cost/risk.

**Owner:** Product/business decision + Backend entitlement policy + Frontend messaging.

---

### 12. Handle/alert invoice finalization failures

**Current:** logged only.

**Fix:** create operational alert/admin-visible billing incident and, where customer action is relevant, communicate it separately from card decline.

**Why:** invoice creation failure can prevent collection even when the customer's card is fine.

**Owner:** Backend/operations.

---

## P2 — Hardening and clarity improvements

### 13. Explicitly handle `checkout.session.expired`

**Current:** audited as unhandled.

**Fix:** optionally record abandoned/expired checkout state for analytics/support and present a clean “session expired, start again” experience if session correlation is added.

**Why:** improves funnel observability and recovery, though current entitlement safety is not broken.

**Owner:** Backend + Frontend optional.

---

### 14. Strengthen abnormal `checkout.session.completed` without subscription handling

**Current:** warning + successful webhook processing.

**Fix:** treat it as an explicit reconciliation incident: retry/error when appropriate or persist an actionable billing alert instead of silently considering it complete.

**Why:** in subscription mode, a completed session without a subscription is unexpected and could leave a customer's payment state disconnected from CEOPRO.

**Owner:** Backend/operations.

---

### 15. Clarify `payment_method` API semantics

**Current:** API accepts `card`, `stripe`, and `googlePay`, but the checkout adapter does not branch/configure Stripe based on these choices; it mainly rejects PayPal.

**Fix:** either:

1. simplify the API to `payment_provider: "stripe"`, letting Stripe Checkout present eligible card/wallet methods; or
2. genuinely map requested payment methods into provider configuration when business requirements need that control.

**Why:** public API fields should have real semantics and not imply behavior the backend does not enforce.

**Owner:** Backend + Frontend contract.

---

### 16. Preserve service-specific error messages when useful

**Current:** several service methods create more precise messages, but controllers often call `sendApiError(resp, result.code)` and discard the service message.

**Fix:** safely pass normalized domain messages where they improve customer actionability.

**Why:** precise business errors such as why a billing period/change cannot proceed are more useful than generic error text.

**Owner:** Backend.

---

### 17. Consider correlating success return with the exact Checkout Session

**Current:** success page only polls the tenant's current subscription.

**Improvement:** include Stripe's `{CHECKOUT_SESSION_ID}` in the success URL and optionally expose a safe backend confirmation endpoint tied to tenant/session.

**Why:** makes support/debugging and exact purchase confirmation stronger, especially if more complex billing flows are added later.

**Owner:** Backend + Frontend. Not required for basic correctness today.

---

# 18. Recommended customer-facing state machine

A clean production UX should present these business states explicitly:

```text
NO SUBSCRIPTION
    ↓ choose plan
CHECKOUT CREATED
    ↓
PAYMENT IN PROGRESS
    ├─ success ─────────────→ ACTIVE
    ├─ trial ───────────────→ TRIALING
    ├─ action required ─────→ ACTION_REQUIRED
    ├─ incomplete ──────────→ PAYMENT_PENDING
    ├─ customer cancelled ──→ CHECKOUT_CANCELLED
    └─ terminal failure ────→ PAYMENT_FAILED

ACTIVE/TRIALING
    ├─ renewal success ─────→ ACTIVE
    ├─ renewal failure ─────→ PAST_DUE / RECOVERY
    ├─ upgrade ─────────────→ APPLYING / ACTION_REQUIRED / ACTIVE
    ├─ downgrade ───────────→ ACTIVE + SCHEDULED_CHANGE
    └─ cancel ──────────────→ ACTIVE/TRIALING + CANCEL_AT_PERIOD_END

PAST_DUE / PAYMENT_FAILED / PENDING
    ├─ recover payment ─────→ ACTIVE
    ├─ terminal expiry ─────→ EXPIRED
    └─ cancel/end ──────────→ CANCELLED
```

The frontend should never collapse all of these into only “success” vs “failure.”

---

# 19. Overall current-state conclusion

The current subscription architecture is fundamentally sound in the important areas:

- server-authoritative plan and promo validation;
- tenant-private custom plans;
- Stripe-hosted payment collection;
- webhook signature verification;
- asynchronous/out-of-order webhook recovery;
- idempotent subscription/payment/promo processing;
- separate current-subscription vs access-granting status concepts;
- correct distinction between invoice settlement and actual monetary payment;
- safe period-end entitlement reductions/downgrades;
- trial preservation during plan changes;
- cancellation at the end of paid access;
- no duplicate subscription checkout while a billing lifecycle is still current.

The major remaining production gaps are mostly **recovery and customer-state UX**, not the core billing data model:

1. successful-return page can falsely confirm a non-active subscription;
2. delinquent customers are blocked from new checkout but lack a clear payment-recovery path;
3. frontend treats all current statuses as active during plan change;
4. immediate paid upgrade can claim the prorated charge succeeded before payment is fully confirmed;
5. scheduled downgrade cancellation is referenced but not exposed as a real action;
6. 3DS/payment-action-required, trial-ending, and invoice-finalization events are logged without complete customer/operations workflows;
7. checkout cancellation is presented as payment failure;
8. standard checkout Stripe exceptions should map to a provider-specific error instead of generic internal error.

Once these are addressed, the customer subscription lifecycle will be much closer to production-grade behavior across happy paths, insufficient funds, card declines, trials, renewals, recovery, plan changes, cancellations, and asynchronous provider failures.
