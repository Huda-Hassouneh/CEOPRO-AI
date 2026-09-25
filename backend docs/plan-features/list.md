# List Plan Features

## Endpoint
`GET /plans/:plan_id/features`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.read` (or `all`).

## Behavior
Returns feature links and limits for a plan.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
