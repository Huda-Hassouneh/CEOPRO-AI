# Validate Promo Code

## 1. Endpoint Details

`POST /subscription/promo-codes/validate`

## 2. Mental Model

Checks whether a promotion can be applied to a specific plan before checkout, including active window, usage limits, and plan applicability.

## 3. Technical Decisions

Validation is tenant-authenticated and requires `manage_billing`, but the service uses the code and plan association as the source of truth. It returns provider coupon data needed by checkout without consuming the code; consumption occurs in later subscription/webhook flow.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_billing`.
- JSON body: `{ "code": "WELCOME10", "planId": "<uuid>" }`; both are required and the object is strict. No path/query parameters.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Promo code is valid",
  "data": {
    "code": "WELCOME10",
    "discountType": "percentage",
    "discountValue": 10,
    "paymentProviderCoupon": "coupon_..."
  }
}
```

### Errors

`404 PROMO_CODE_NOT_FOUND`: `Promo code not found`.

`422 PROMO_CODE_NOT_ACTIVE`, `PROMO_CODE_EXPIRED`, `PROMO_CODE_USAGE_LIMIT_REACHED`, or `PROMO_CODE_NOT_APPLICABLE` with the matching definitions in `errors/error-defentions.ts`.

Validation/security failures use the common `400`, `401`, and `403` envelopes.
