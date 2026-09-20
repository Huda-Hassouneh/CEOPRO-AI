# Current Usage Dashboard

## 1. Endpoint Details

`GET /subscriptions/current/usage`

## 2. Mental Model

Builds the tenant's current entitlement dashboard: active plan, billing window, each feature's limit, current usage, remaining capacity, and whether a quota is exceeded.

## 3. Technical Decisions

The repository directly queries the tenant's active subscription, plan features, and usage records for the current time window. The service maps Prisma data into a frontend-specific shape and returns `unlimited` for null limits. Tenant identity is derived from JWT context.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Usage dashboard retrieved successfully",
  "data": {
    "plan": {
      "id": "<uuid>",
      "name": "Pro",
      "status": "active",
      "period_start": "2026-09-01T00:00:00.000Z",
      "period_end": "2026-10-01T00:00:00.000Z"
    },
    "entitlements": [
      {
        "feature_code": "ai_pricing",
        "name": "AI Pricing",
        "type": "limit",
        "limit": 100,
        "current_usage": 12,
        "remaining": 88,
        "is_exceeded": false,
        "unit": "requests",
        "aggregation_type": "sum",
        "reset_cycle": "billing_period"
      }
    ]
  }
}
```

### Errors

`404 SUBSCRIPTION_NOT_FOUND`: `Subscription not found`.

`400 INVALID_REQUEST`: `Tenant context missing.`

`500 INTERNAL_SERVER_ERROR`: `An unexpected error occurred`; common auth/permission failures also apply.
