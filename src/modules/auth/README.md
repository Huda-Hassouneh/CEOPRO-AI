# Auth Domain

## Purpose
Owns authentication/session HTTP endpoints and platform invitation acceptance.

## Structure
- `index.ts` is the domain entry point.
- `route/` contains the existing login, session, logout, invitation lookup, and invitation acceptance routes.

## Current flow
`HTTP -> auth route -> shared auth/session utilities + Prisma / owner-portal invitation service`

## Important decisions
- Existing authentication behavior is preserved exactly in this structural pass; the login throttling map, token generation, session persistence, invitation behavior, and response contract were not redesigned.
- The route remains self-contained because splitting the existing handler into new service/repo functions would be a behavioral refactor rather than a path-only reorganization.
- Tenant and session validation continue to use the shared middleware in `src/validators`.
- Platform invitation business rules remain owned by `owner-portal`; auth only exposes the invitation-facing HTTP endpoints.

## Data touched
`User`, `TenantUser`, `Company`, and `AuthSession` through the current Prisma calls.

## Integration notes
There is no external AI integration in this domain.
