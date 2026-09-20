# List Features

## 1. Endpoint Details

`GET /features`

## 2. Mental Model

Lists the system entitlement catalog used to define what each subscription plan grants, such as boolean access or metered quotas.

## 3. Technical Decisions

The route is authenticated, tenant-scoped, and restricted to `manage_catalog`. The controller delegates to `featureService`, which delegates persistence to `featureRepository`; the route exposes the repository result through the shared response helper.

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
  "message": "Features retrieved successfully",
  "data": [
    {
      "id": "<uuid>",
      "feature_code": "ai_pricing",
      "name": "AI Pricing",
      "type": "limit"
    }
  ]
}
```

### Errors

`500 INTERNAL_SERVER_ERROR`: `An unexpected error occurred`, plus common `401 INVALID_AUTH_HEADER`/`INVALID_TOKEN`, `400 INVALID_REQUEST`, and `403 FORBIDDEN` failures.
