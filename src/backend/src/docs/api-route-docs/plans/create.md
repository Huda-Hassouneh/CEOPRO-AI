# Create Subscription Plan

## 1. Endpoint Details

`POST /subscription/plans`

## 2. Mental Model

Creates a catalog plan and its Stripe prices so future checkout and plan-change flows can reference provider price IDs.

## 3. Technical Decisions

The route requires `all` permission, validates a strict plan DTO, checks duplicate names through the repository, creates one Stripe price per billing option, then persists the enriched plan. This intentionally coordinates the external provider before the local catalog insert.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `all` (or a role's master override).
- JSON body: `name`, `name_ar` strings 1-50; `tierLevel` positive integer; optional `description`, `description_ar`; `price` nonnegative number with max 2 decimals; `currency` uppercase 3-letter code; `billingIntervalValue` positive integer; `billingIntervalUnit: day|week|month|year`; optional `isActive` boolean and `trialPeriodValue` nonnegative integer; required `billingOptions` array of `{ period: string, months: positive integer, discountPercent: 0-100 }` with at least one item.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "message": "Plan created successfully",
  "data": {
    "id": "<uuid>",
    "name": "Pro",
    "billingOptions": [
      {
        "period": "monthly",
        "months": 1,
        "discountPercent": 0,
        "stripePriceId": "price_..."
      }
    ]
  }
}
```

### Errors

`409 RESOURCE_ALREADY_EXISTS`: `Resource already exists` for duplicate names.

`422 UNPROCESSABLE_ENTITY`: `At least one billing option must be provided.`

`400 VALIDATION_ERROR` for DTO failures; `502 PAYMENT_PROVIDER_ERROR`/`EXTERNAL_SERVICE_ERROR` for Stripe failures; common `401`, `400 INVALID_REQUEST`, and `403 FORBIDDEN` for security failures.
