# Get Feature

## Endpoint
`GET /features/:id`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.read` (or `all`).

## Behavior
Returns one feature definition by UUID.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
