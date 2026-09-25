# Change Current Subscription Plan

## Endpoint
`PATCH /subscription/current/plan`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Input
Strict body validated by `changePlanSchema`; includes the target `planId` and requested billing period.

## Transition logic
The service loads both current and target plans with `planFeatures` and runs `analyzePlanTransition()`.

- absent -> present, quota increase, limited -> unlimited: gain.
- present -> absent, quota reduction, unlimited -> limited: loss.
- gains only: `upgrade`.
- losses only: `downgrade`.
- gains and losses: `mixed`.
- no entitlement changes: `equivalent`.

Any entitlement loss produces `effectiveTiming = "period_end"`. Gain-only changes may be immediate. If entitlement data is unavailable/legacy, tier, price, and billing duration remain the compatibility fallback.

## Stripe behavior
Immediate changes use the existing subscription-update path. Period-end changes use the safe schedule path (the Stripe service's `downgrade` action), including `mixed` transitions.

Trialing immediate upgrades preserve the existing trial end and do not charge immediately. Paid immediate upgrades use the normal prorated-charge behavior implemented by the Stripe service.

## Local state / response
For period-end changes:
- `Subscription.planId` stays current.
- `scheduledPlanId` and `scheduledBillingPeriod` are populated.
- response `transitionType` may be `upgrade`, `downgrade`, `mixed`, or `equivalent`.
- `effectiveAt` is the current period end.
- `entitlementAnalysis` includes gains/losses.

For immediate changes, scheduled fields are cleared and Stripe/webhook synchronization updates the authoritative subscription state.
