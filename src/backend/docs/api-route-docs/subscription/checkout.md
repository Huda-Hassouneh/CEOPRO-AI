# Subscription Checkout

## 1. Endpoint Details

`POST /subscription/checkout`

## 2. Mental Model

Starts a new tenant subscription by validating an optional promotion, selecting a plan billing option, creating/reusing the payment customer, and returning a Stripe Checkout URL. The subscription record is completed asynchronously by webhook processing.

## 3. Technical Decisions

The route validates the body with a strict Zod schema and requires `manage_catalog`. The service rejects an existing tenant subscription before creating checkout, uses the plan's stored billing option and Stripe price, and passes tenant identity in Stripe session metadata. Provider/database work is coordinated through service and repository layers; the provider is not trusted as the synchronous source of local subscription state.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>`; JWT must contain `tenant_id`, `id`, and `email`.
- Permission: `manage_catalog` or `all`.
- JSON body:

```json
{
  "planId": "<uuid>",
  "billing_period": "monthly",
  "payment_method": "stripe",
  "promoCode": "WELCOME10"
}
```

`planId: string<uuid>` and `billing_period: "monthly" | "three-months" | "six-months" | "yearly"` are required. `payment_method: "card" | "stripe" | "googlePay" | "paypal"` is required by validation. `promoCode: string` is optional, 1-50 characters.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Checkout session created successfully",
  "data": { "checkoutUrl": "https://checkout.stripe.com/..." }
}
```

### Errors

`400 VALIDATION_ERROR` for missing/invalid body fields; `404 PROMO_CODE_NOT_FOUND` or `422 PROMO_CODE_NOT_ACTIVE`, `PROMO_CODE_EXPIRED`, `PROMO_CODE_USAGE_LIMIT_REACHED`, or `PROMO_CODE_NOT_APPLICABLE` for promotion failures; `409 SUBSCRIPTION_ALREADY_EXISTS` when the tenant already has a subscription; `400` for a billing period absent from the plan; `502 PAYMENT_PROVIDER_ERROR`/`EXTERNAL_SERVICE_ERROR` for provider failures. Auth and permission failures use the common `401`, `400 INVALID_REQUEST`, or `403 FORBIDDEN` envelopes.
