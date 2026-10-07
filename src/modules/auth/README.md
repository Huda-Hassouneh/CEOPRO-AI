# Authentication Domain

## Purpose

Owns registration, login, session, password, and invitation HTTP endpoints. The router is mounted at `/auth`.

## Routes

- `POST /auth/register` creates only a `pending_signups` row and sends a verification email through the configured provider. It does not create a user, tenant, membership, or session. Public registration cannot create a `platform` tenant.
- Verification emails link directly to `FRONTEND_URL/verify-email?token=...`. The frontend displays a confirmation button and submits to `POST /auth/verify-email/confirm` only after the user clicks it; this avoids email scanners confirming accounts from a GET request. The backend then creates the user, customer tenant, first `owner` membership, and a short-lived one-time frontend exchange grant, and redirects to `/verify-email?code=...` on `FRONTEND_URL`.
- `GET /auth/verify-email?token=...` remains available as a backend-hosted confirmation page, but verification emails do not link to it.
- `POST /auth/verification/exchange` consumes the one-time code and returns the normal login session response. The frontend saves that session and navigates to `/onboarding`.
- `POST /auth/verification/resend` requests another verification email. Responses do not disclose whether an email address is registered; resend is throttled.
- `POST /auth/login` selects the platform workspace only for a platform owner; users with a customer membership are issued a customer-tenant session.
- `GET /auth/me` and `GET /auth/session` require an active authenticated tenant membership.
- `POST /auth/change-password` verifies the current password, updates the hash, and revokes other persisted sessions.
- `POST /auth/logout` revokes the current persisted session.
- Invitation lookup and acceptance remain delegated to `owner-portal` business rules.

## Structure

`route/` handles HTTP validation and middleware, `controller/` maps requests to services, `service/` handles auth/session flows, and `repo/` owns Prisma operations.

## Security notes

- JWTs are verified with HS256 only.
- Protected requests with a session ID require a matching unrevoked, unexpired `auth_sessions` row.
- First-tenant membership creation sets transaction-local tenant/user context for the onboarding RLS policy.
- Passwords are limited to 72 UTF-8 bytes before bcrypt hashing to avoid silent truncation.
- Verification links and frontend exchange codes are random, single-use, stored only as SHA-256 hashes, and expire after 30 minutes and 10 minutes respectively.
- Set `EMAIL_DELIVERY_PROVIDER=gmail_smtp` for testing with Gmail, plus `GMAIL_SMTP_USER` and a Google App Password in `GMAIL_SMTP_APP_PASSWORD`. Keep these secrets in the backend environment only. Gmail delivery uses implicit TLS on port 465.
- To switch back to Resend, set `EMAIL_DELIVERY_PROVIDER=resend` and configure `EMAIL_SERVICE_PROVIDER_API_KEY` and `EMAIL_SERVICE_PROVIDER_FROM_EMAIL`. Resend continues to use its existing REST API client.
- Configure `FRONTEND_URL` for both the email link and post-confirmation redirect. Configure the frontend's `VITE_API_BASE_URL` to point to the backend so the confirmation form reaches the backend endpoint.

## Data touched

`PendingSignup`, `EmailVerificationGrant`, `User`, `TenantUser`, `Company`, and `AuthSession`.
