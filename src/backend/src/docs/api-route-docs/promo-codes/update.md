# Update Promo Code

## 1. Endpoint Details

`PATCH /subscription/promo-codes/:id`

## 2. Mental Model

Changes promotion metadata and refreshes its Stripe coupon/provider representation so future checkout uses the updated discount.

## 3. Technical Decisions

The route uses the existing plan UUID validator for `id` (the source comments note this DTO should be renamed). The partial strict body requires at least one field and preserves paired discount/date/usage invariants. The service checks existence and duplicate code, then calls Stripe and stores the new provider coupon ID.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- Path: `id: string<uuid>`.
- JSON body: optional subset of `code`, `discountType`, `discountValue`, `maxUses`, `maxUsesPerUser`, `startsAt`, `expiresAt`, `isActive`; at least one field. `discountType` and `discountValue` must appear together.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Promocode updated successfully",
  "data": { "id": "<uuid>", "code": "WELCOME20" }
}
```

### Errors

`404 PROMO_CODE_NOT_FOUND`: `Promo code not found`.

`409 RESOURCE_ALREADY_EXISTS`: `Resource already exists` for a code collision.

`400 VALIDATION_ERROR` for invalid path/body; provider failures use their service-defined code/status; common security errors apply.
