# Preview Custom Plan

## Endpoint
`POST /subscription/custom-plans/preview`

## Authorization
Authenticated user + active tenant membership.

## Body
`features[]` with `featureId` and optional `limitValue`, plus `billingPeriod`.

## Behavior
The server recalculates price from the current pricing policy and vendor rates. For limit features, customer `limitValue` is also used as the automated estimated usage input in the current self-service model. The response includes customer-safe totals, selected normalized features, billing duration/discount, and `eligibleForInstantCheckout` plus manual-review reason codes.

The preview is informative; checkout recalculates again and does not trust browser-supplied money.
