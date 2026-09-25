# Link Feature to Plan

## Endpoint
`POST /plans/:plan_id/features`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Creates a PlanFeature association.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
