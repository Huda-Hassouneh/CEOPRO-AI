# Current Subscription Usage / Entitlements

## Endpoint
`GET /subscriptions/current/usage`

## Authorization
Authenticated user + active tenant membership. No extra `manage_catalog`/platform permission is required.

## Behavior
Builds the tenant's current entitlement dashboard from the active subscription and `PlanFeature` configuration. It distinguishes:

- boolean access;
- SUM consumption/remaining quota;
- MAX live capacity/remaining capacity;
- unlimited limits (`limitValue = null`).

The frontend uses this response for feature gates and action locks. Backend consuming routes still enforce entitlements independently.
