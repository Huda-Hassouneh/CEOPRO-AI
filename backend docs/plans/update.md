# Update Standard Plan

## Endpoint
`PATCH /subscription/plans/:id`

## Authorization
Authenticated active membership with `roleKey=owner` + `billing.manage` (or `all`).

## Behavior
Updates allowed standard-plan fields after UUID/body validation. Accepted tenant-specific Custom Plans are protected by service rules and are not ordinary editable standard plans.
