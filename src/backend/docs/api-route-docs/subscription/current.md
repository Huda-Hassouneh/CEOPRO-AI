# Current Subscription

## 1. Endpoint Details

`GET /subscription/current`

## 2. Mental Model

Returns the authenticated tenant's active subscription, allowing the SaaS UI to render current plan, billing period, provider identifiers, and lifecycle state.

## 3. Technical Decisions

Tenant identity comes from the verified JWT, not a client-supplied parameter. The service queries the active subscription through `subscriptionRepo` and requires a provider subscription ID because subsequent billing actions depend on Stripe linkage.

## 4. Inputs

- Required header: `Authorization: Bearer <JWT>`.
- JWT requirement: `tenant_id` claim.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Subscription fetched successfully",
  "data": {
    "id": "<uuid>",
    "tenantId": "<uuid>",
    "planId": "<uuid>",
    "status": "active",
    "paymentProviderSubscriptionId": "sub_..."
  }
}
```

`data` is the Prisma `Subscription` record.

### Errors

`404 SUBSCRIPTION_NOT_FOUND` (`Subscription not found`) or `400 PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND` (`Payment provider subscription ID is missing`). Missing/invalid authentication returns `401 INVALID_AUTH_HEADER` or `401 INVALID_TOKEN`; missing tenant context returns `400 INVALID_REQUEST`.
