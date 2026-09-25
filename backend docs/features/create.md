# Create Feature

## Endpoint
`POST /features`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Creates a feature definition using the strict feature DTO.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
