# Update Feature

## Endpoint
`PATCH /features/:id`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Updates an existing feature definition.

Global catalog operations are platform-commercial actions; the latest code no longer documents them as ordinary tenant `manage_catalog` routes.
