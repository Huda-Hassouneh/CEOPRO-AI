# List Promo Codes

## Endpoint
`GET /subscription/promo-codes`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.read` (or `all`).

## Behavior
Lists platform promo codes.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
