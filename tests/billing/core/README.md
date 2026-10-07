# Billing Core Tests

Fast, focused tests for billing/subscription contracts that do not require a live Stripe account or database connection.

| File | What it tests |
| --- | --- |
| `admin-tenant-billing-permission.test.ts` | Migration grants tenant `admin` the canonical `manage_billing` permission, and checkout remains protected by the tenant-scoped `manage_billing` route boundary. |
| `checkout-schema.test.ts` | Checkout DTO accepts the public `payment_method` contract and rejects unknown/legacy-mismatched fields. |
| `currency.test.ts` | Stripe currency exponent rules plus symmetric major↔minor unit conversion, including zero-decimal currencies. |
| `plan-pricing.test.ts` | Monthly/yearly option pricing, duplicate option protection, unsupported daily billing, and catalog amount behavior. |
| `plan-transition.test.ts` | Entitlement-aware plan transition classification: gains, losses, mixed changes, limit increases/decreases, removed features, identical plans, and provider-plan identity. |
| `subscription-recovery-policy.test.ts` | Which payment-problem subscription states are recoverable and which access/terminal states must not enter recovery. |
| `subscription-status.test.ts` | Only `active` and `trialing` grant entitlement access; non-access lifecycle states do not. |

## Run

From backend root:

```bash
node --import tsx --test tests/billing/core/<file>.test.ts
```
