# List Promo Codes

## 1. Endpoint Details

`GET /subscription/promo-codes`

## 2. Mental Model

Provides billing/catalog administrators with the current promotion catalog for management and checkout configuration.

## 3. Technical Decisions

Authentication and tenant context are applied at router scope, while authorization requires `all`. The controller delegates the list to a service/repository query and returns persisted promo records without accepting client filters.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `all`.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Promocodes fetched successfully",
  "data": [
    {
      "id": "<uuid>",
      "code": "WELCOME10",
      "discountType": "percentage",
      "discountValue": 10,
      "isActive": true
    }
  ]
}
```

### Errors

`500 INTERNAL_SERVER_ERROR` or another service-defined code in the common error envelope. Authentication, tenant, and permission errors use `INVALID_AUTH_HEADER`, `INVALID_TOKEN`, `INVALID_REQUEST`, or `FORBIDDEN`.
