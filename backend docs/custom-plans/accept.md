# Accept Manual Custom Plan Offer

## Endpoint
`POST /subscription/custom-plans/quotes/:id/accept`

## Authorization
Authenticated tenant + `manage_catalog` (or `all`) in the **current code**.

## Important inconsistency
The self-service Custom Plan manual-review/checkout routes use `manage_billing`, but this legacy manual-offer acceptance route still requires `manage_catalog`. Documentation keeps that mismatch visible so integration code does not assume otherwise.

## Behavior
Accepts an eligible tenant-scoped offer and materializes the tenant-specific immutable Custom Plan definition. Subscription activation/change is still a separate subscription lifecycle concern.
