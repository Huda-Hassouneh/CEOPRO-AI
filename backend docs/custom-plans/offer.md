# Get Customer-Safe Custom Quote Offer

## Endpoint
`GET /subscription/custom-plans/quotes/:id/offer`

## Authorization
Authenticated user + active tenant membership. Quote lookup is tenant-scoped.

## Behavior
Returns only customer-safe commercial offer data. Internal vendor-cost, margin-floor, pricing-policy, and other platform economics remain hidden.
