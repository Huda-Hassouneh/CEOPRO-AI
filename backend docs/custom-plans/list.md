# List Tenant Custom Plans

## Endpoint
`GET /subscription/custom-plans`

## Authorization
Authenticated user + active tenant membership.

## Behavior
Returns Custom Plan definitions private to the authenticated tenant. Plan-definition `isActive` means Enabled/Disabled, not current subscription status.
