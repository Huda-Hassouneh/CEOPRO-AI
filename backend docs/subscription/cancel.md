# Schedule Subscription Cancellation

## Endpoint
`PATCH /subscription/current/cancel`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Behavior
Schedules cancellation at the end of the current billing period through Stripe. A scheduled plan change is not treated as cancellation; cancellation truth is `cancelAtPeriodEnd`/provider state.
