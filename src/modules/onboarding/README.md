# Onboarding Domain

## Purpose
Owns the tenant onboarding wizard: regional preferences, business profile, strategic goals, plan selection, and data-source setup.

## Structure
- `index.ts` is the domain entry point, mounted at `/onboarding`.
- `route/` declares the endpoints; every route requires `authenticateUser` and `requireTenant`.
- `controller/` maps HTTP to the service; `service/` enforces step ordering; `repo/` reads and writes the `onboarding` table.
- `types/` holds the zod request schemas.

## Current flow
`HTTP -> onboarding route -> controller -> service -> repo -> onboarding / companies / users`

## Important decisions
- State is one row per tenant in `onboarding`, created lazily on first read.
- Steps must be completed in order; skipping ahead returns `ONBOARDING_INCOMPLETE`.
- Saving regional preferences also updates the company's country, currency, timezone and language, and the user's preferred language, in one transaction.
- This is unrelated to `POST /subscription`, which is the one-time Stripe account onboarding.

## Data touched
`onboarding` (raw SQL), `Company`, and `User`.

## Integration notes
There is no external AI integration in this domain.
