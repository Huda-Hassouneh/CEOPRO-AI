# CEOPRO Frontend Billing Production Tests

This suite verifies that the customer-facing billing/onboarding frontend is aligned with the production standard-plan catalog while preserving the separate Custom Plan flow.

## Run

```powershell
npm run test:billing:frontend
```

Full frontend release check:

```powershell
npm run test:billing:frontend:release
```

The full command runs the existing subscription integration verification, entitlement verification, this suite, and the Vite production build.

## Groups

- 34 — Production catalog source: standard plans are loaded from `/subscription/plans`; no preview/mock catalog is used by customer billing pages.
- 35 — Tier names + i18n: Starter/Growth/Enterprise/Custom copy exists in English and Arabic; legacy Standard/Pro two-tier copy is rejected; RAG quota copy must be token-based.
- 36 — Billing periods + currency: 1/3/6 month period behavior remains correct; plan cards render backend currency; standard-plan admin form must not default to unsupported JOD.
- 37 — Custom Plan preserved: Custom remains a separate builder route in billing and onboarding and its checkout remains server-authoritative.
- 38 — Checkout authority: frontend sends plan identity/period/payment method, not amount/price/currency.
- 39 — Onboarding success: success routes remain wired and both standard/custom onboarding payment paths exist.
- 40 — Production UI guard: no Development Showcase/preview catalog leaks into customer billing, production tier names are understood, and standard customer surfaces do not hardcode JOD.

## Expected first run

The current frontend is expected to expose a few real alignment gaps, especially legacy `Standard` / `Pro` localized copy and the Owner standard-plan form's JOD default. Those should be fixed rather than weakening the tests.
