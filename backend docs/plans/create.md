# Create Standard Plan

## Endpoint
`POST /subscription/plans`

## Authorization
Authenticated active membership with `roleKey=owner` + platform permission `billing.manage` (or `all`).

## Behavior
Creates a standard catalog plan from the strict plan DTO and its billing options. This is a platform-commercial mutation, not a normal tenant `manage_catalog` action.
