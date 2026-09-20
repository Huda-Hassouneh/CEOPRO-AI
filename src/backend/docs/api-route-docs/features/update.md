# Update Feature

## 1. Endpoint Details

`PATCH /features/:id`

## 2. Mental Model

Edits entitlement metadata without changing the immutable feature code, protecting existing plan links and application entitlement references.

## 3. Technical Decisions

The route validates a UUID and strict partial DTO. The controller maps `aggregation_type` and `reset_cycle` to service field names and deliberately does not accept `code`. The service verifies existence before updating through the repository.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- Path: `id: string<uuid>`.
- JSON body: optional subset of `name`, `name_ar`, `description`, `description_ar`, `type`, `unit`, `unit_ar`, `aggregation_type`, `reset_cycle`; unknown fields are rejected.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Feature updated successfully",
  "data": { "id": "<uuid>", "name": "AI Pricing" }
}
```

### Errors

`404 RESOURCE_NOT_FOUND`: `Resource not found` with detail `The feature you are trying to update does not exist.`

`400 VALIDATION_ERROR` or `500 INTERNAL_SERVER_ERROR`; security failures use the common envelopes.
