# Current Subscription

## Endpoint
`GET /subscription/current`

## Authorization
Authenticated user + active tenant membership. No extra named permission.

## Behavior
Returns the tenant's newest current subscription and includes both the **current plan** and any **scheduled plan**, each with plan-feature metadata. The service rejects a current row that lacks `paymentProviderSubscriptionId` because later billing actions depend on Stripe linkage.

A scheduled plan does not replace the current plan in this response: `planId`/`plan` stay current until the scheduled transition is actually applied.

## Important fields
- `planId`, `plan`: current effective plan.
- `scheduledPlanId`, `scheduledPlan`: future period-end target, when present.
- `currentPeriodEnd`: also used as the scheduled effective date by the UI.
- `status`, `billingPeriod`, `cancelAtPeriodEnd`, provider IDs.

## Errors
`SUBSCRIPTION_NOT_FOUND`, `PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND`, authentication/tenant errors, or common server errors.
