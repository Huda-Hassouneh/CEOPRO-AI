# List Feature Catalog

## Endpoint
`GET /features`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.read` (or `all`).

## Behavior
Lists the global feature definitions.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
