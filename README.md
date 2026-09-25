# CEOPRO AI Frontend

A Vite + React + TanStack Query starter matching the requested CEOPRO AI frontend architecture.

## Available Scripts

- `npm run dev`
- `npm run build`
- `npm run preview`

## Custom Plan Subscription UX

Custom-plan quoting is integrated into the existing Billing/Subscription Catalog and intentionally reuses the application's shared UI primitives. Internal prices and pricing floors are returned by the backend; the browser only submits configuration/usage assumptions and displays authoritative results.

The customer-facing custom offer shows features, limits, terms, and final selling price without exposing internal vendor rates or margins. Accepted custom plans then use the existing checkout/subscription experience.

See `../CUSTOM_PLAN_IMPLEMENTATION.md` and `../CUSTOM_PLAN_BUSINESS_MODEL.md` for the end-to-end flow.
