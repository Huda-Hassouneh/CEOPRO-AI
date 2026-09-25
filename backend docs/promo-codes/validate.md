# Validate Promo Code

## Endpoint
`POST /subscription/promo-codes/validate`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Behavior
Validates the code against the requested plan and authenticated tenant before checkout. Tenant identity is not accepted from the client as an authority.
