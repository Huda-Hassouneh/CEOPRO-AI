# Create Promo Code

## 1. Endpoint Details

`POST /subscription/promo-codes`

## 2. Mental Model

Creates a promotion in the local catalog and creates the corresponding Stripe coupon/provider object used when checkout applies the code.

## 3. Technical Decisions

The strict DTO enforces date ordering, usage-limit consistency, discount precision, and percentage bounds before the service checks code uniqueness. Stripe creation occurs before the Prisma insert, and the provider coupon ID is stored with the local record.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `all`.
- JSON body: `{ "code": "WELCOME10", "discountType": "percentage" | "fixed_amount", "discountValue": number, "maxUses": positive integer, "maxUsesPerUser": positive integer, "startsAt": ISO date, "expiresAt": ISO date, "isActive": boolean }`. `code` is 1-50 alphanumeric/underscore/hyphen and is uppercased; percentage values cannot exceed 100; `expiresAt` must follow `startsAt`.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "message": "Promocode created successfully",
  "data": {
    "id": "<uuid>",
    "code": "WELCOME10",
    "paymentProviderCoupon": "coupon_..."
  }
}
```

### Errors

`409 RESOURCE_ALREADY_EXISTS`: `Resource already exists`.

`400 VALIDATION_ERROR` for schema errors; `502 PAYMENT_PROVIDER_ERROR`/provider errors for Stripe failures; common security errors apply.
