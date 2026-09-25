# Undo Scheduled Cancellation

## Endpoint
`PATCH /subscription/current/cancel/undo`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Behavior
Clears a previously scheduled period-end cancellation through the Stripe service while preserving independent scheduled plan-change semantics.
