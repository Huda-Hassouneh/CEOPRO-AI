# Stripe Onboarding

## 1. Endpoint Details

`POST /subscription/`

## 2. Mental Model

Initializes the Stripe product/configuration integration used by the subscription module. It is an application-level setup operation, not a tenant checkout operation.

## 3. Technical Decisions

The service checks the app-config table before calling Stripe, preventing duplicate onboarding and unnecessary external calls. On success it stores the returned Stripe configuration key through the repository layer. The route is protected by JWT authentication, active tenant membership, and the `all` permission because onboarding mutates application-level Stripe configuration.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with an active `tenant_id`.
- Permission: `all`.
- Path/query/body: none.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "data": null,
  "message": "<stripe config key> inserted successfully."
}
```

### Errors

`409 Conflict`:

```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_ALREADY_EXISTS",
    "message": "Resource already exists",
    "statusCode": 409
  }
}
```

`502 Bad Gateway` for Stripe setup failure:

```json
{
  "success": false,
  "error": {
    "code": "EXTERNAL_SERVICE_ERROR",
    "message": "External service error",
    "statusCode": 502
  }
}
```
