# Create Subscription Checkout

## Endpoint
`POST /subscription/checkout`

## Authorization
Authenticated tenant + `manage_billing` (or `all`).

## Behavior
Validates the requested active plan and billing option, prevents creating a second current subscription, validates an optional promo code, and creates the Stripe Checkout flow using stored server-side plan pricing.

Custom plans are tenant-private: a browser-supplied custom `planId` is accepted only when that plan belongs to the authenticated tenant.

`paypal` is rejected by the current payment integration. Card/Google Pay are payment methods handled through Stripe Checkout when available.

## Security
The browser never supplies an authoritative price. Stripe/session metadata carries tenant identity for webhook reconciliation.
