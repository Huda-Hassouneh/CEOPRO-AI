# Owner Portal Domain

## Purpose
Owns platform workspace operations for overview, companies, users, admin-team management, audit logs, settings, profile/password, sessions, and invitations.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with platform-role definitions in `types/`.

## Important decisions
- Platform permission checks remain route/controller enforced through the existing shared validator.
- The single-owner protections and owner role restrictions remain unchanged.
- Read and write services stay separated because they have distinct responsibilities and transaction patterns.
- Invitation, audit, team, settings, and session behavior is preserved exactly.
- `platform-roles.ts` was moved into `types/` because it is a domain contract/configuration definition rather than a root module entry point.

## Cross-domain usage
`platform-admin` mounts this router after platform authentication/role middleware. Auth invitation endpoints reuse owner-portal invitation services.
