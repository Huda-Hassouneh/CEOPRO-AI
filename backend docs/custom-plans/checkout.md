# Custom Plan Checkout / Existing-Subscription Change

## Endpoint
`POST /subscription/custom-plans/checkout`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Behavior
1. Recalculates the configuration on the server.
2. Creates/reuses the automatic quote keyed by `requestId`.
3. If manual review is now required, returns `manualReviewRequired: true` instead of checkout.
4. Otherwise creates/accepts the tenant-specific Custom Plan definition.
5. If the tenant has no current subscription, creates the normal Stripe Checkout flow.
6. If the tenant already has a current subscription, calls the normal plan-change service and returns `subscriptionChanged: true` with transition metadata.

For an existing subscription, `transition.effectiveTiming` may be `immediate` or `period_end`. A `mixed` transition with any entitlement loss is period-end; the current plan remains active until then.
