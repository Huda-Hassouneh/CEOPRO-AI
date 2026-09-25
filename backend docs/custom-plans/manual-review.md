# Request Custom Plan Manual Review

## Endpoint
`POST /subscription/custom-plans/manual-review`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Body
Preview fields plus a UUID `requestId`.

## Behavior
Recalculates authoritatively. The request is accepted only when the configuration actually triggers a manual-review reason, such as an automatic price/quota threshold or vendor-rate verification concern. The `requestId` is idempotency/configuration identity: reusing it for a different configuration or pricing fingerprint is rejected.
