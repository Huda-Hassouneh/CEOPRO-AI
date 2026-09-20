# Create Feature

## 1. Endpoint Details

`POST /features/`

## 2. Mental Model

Adds a new entitlement definition to the SaaS catalog. Plans can subsequently link this feature with a boolean grant or numeric limit.

## 3. Technical Decisions

The strict DTO constrains codes to lowercase letters, numbers, and underscores and models type/aggregation/reset semantics. The service checks code uniqueness before repository insertion. The route requires `manage_catalog` and uses a consistent success/error helper.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- JSON body: required `code: string` (3-50, lowercase `[a-z0-9_]`), `name: string` (2-100), `name_ar: string` (2-100), `type: "boolean" | "limit"`; optional `description`, `description_ar` (max 500), `unit`, `unit_ar` (max 50), `aggregation_type: "sum" | "max"`, and `reset_cycle: "billing_period" | "lifetime"`.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "message": "Feature created successfully",
  "data": { "id": "<uuid>", "feature_code": "ai_pricing", "type": "limit" }
}
```

### Errors

`409 RESOURCE_ALREADY_EXISTS`: `Resource already exists` for duplicate code.

`400 VALIDATION_ERROR` for schema failures; `500 INTERNAL_SERVER_ERROR` for repository failures; security failures use the common envelopes.
