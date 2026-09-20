# Link Promo Code to Plan

## 1. Endpoint Details

`POST /subscription/promo-codes/:promoCodeId/plans/:planId`

## 2. Mental Model

Associates an existing promotion with an allowed subscription plan, constraining where the discount can be used.

## 3. Technical Decisions

Both identifiers are validated as UUIDs and authorization requires `all`. The service/repository layer owns the join-table mutation and duplicate behavior, keeping relationship persistence out of the controller.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `all`.
- Path: `promoCodeId: string<uuid>`, `planId: string<uuid>`.
- Query/body: none.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "message": "Promo code linked to plan successfully",
  "data": null
}
```

### Errors

`400 VALIDATION_ERROR` for invalid IDs; `404 PROMO_CODE_NOT_FOUND` or `PLAN_NOT_FOUND` when referenced records are absent; `409 RESOURCE_ALREADY_EXISTS` for a duplicate association; other service errors use the common envelope.
