# Tenant Invoices

## 1. Endpoint Details

`GET /subscription/invoices`

## 2. Mental Model

Returns a tenant-facing billing history assembled from paid Stripe invoice webhook audit events, giving the UI stable invoice IDs, dates, amounts, status, and hosted/PDF links.

## 3. Technical Decisions

The service first resolves the tenant's active subscription and Stripe subscription ID, then queries the webhook-event table directly through `invoiceRepo`. It maps Stripe Unix timestamps and cents into ISO dates and normal currency units. Tenants without a provider subscription receive an empty list rather than an error.

## 4. Inputs

- Required header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Invoices retrieved successfully",
  "data": [
    {
      "id": "in_...",
      "date": "2026-09-20T12:00:00.000Z",
      "amount": 99,
      "currency": "usd",
      "status": "paid",
      "pdfUrl": "https://...",
      "hostedUrl": "https://..."
    }
  ]
}
```

No active subscription/provider ID returns `data: []`.

### Errors

`401 UNAUTHORIZED` if tenant context is absent; `500 INTERNAL_SERVER_ERROR`: `An unexpected error occurred` for query/mapping failure. Invalid auth and tenant errors use the common security envelopes.
