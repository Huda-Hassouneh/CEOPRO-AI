# Auth Domain

## Purpose
Owns authentication/session HTTP endpoints (register, login, current user, change password, logout) and platform invitation acceptance. Mounted at `/auth`.

## Structure
- `index.ts` is the domain entry point.
- `route/` declares every auth endpoint; login, session, logout and the invitation routes are handled inline.
- `controller/`, `service/`, `repo/` and `types/` back register, `/me` and change-password.
- `service/auth.service.ts#issueSession` creates the `AuthSession` and token for both login and register, so they return the same `{ session }` body.

## Current flow
`HTTP -> auth route -> shared auth/session utilities + Prisma / owner-portal invitation service`

## Important decisions
- Existing authentication behavior is preserved exactly in this structural pass; the login throttling map, token generation, session persistence, invitation behavior, and response contract were not redesigned.
- The route remains self-contained because splitting the existing handler into new service/repo functions would be a behavioral refactor rather than a path-only reorganization.
- Self-registration creates a user, a company and an `owner` membership in one transaction. `businessType: "platform"` is rejected because it would grant platform admin access.
- Changing the password bumps `sessionVersion` and revokes every other session of the user.
- Tenant and session validation continue to use the shared middleware in `src/validators`.
- Platform invitation business rules remain owned by `owner-portal`; auth only exposes the invitation-facing HTTP endpoints.

## Data touched
`User`, `TenantUser`, `Company`, and `AuthSession` through the current Prisma calls.

## Integration notes
There is no external AI integration in this domain.
