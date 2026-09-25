# Update Plan Feature Limits

## Endpoint
`PATCH /plans/:plan_id/features/:feature_id`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Updates the linked feature limit configuration.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
