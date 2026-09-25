# Link Promo Code to Plan

## Endpoint
`POST /subscription/promo-codes/:promoCodeId/plans/:planId`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Links a promo code to a plan.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
