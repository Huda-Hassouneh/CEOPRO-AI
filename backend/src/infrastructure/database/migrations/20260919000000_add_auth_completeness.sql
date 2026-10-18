-- CEOPRO AI - Auth completeness: signup, password reset, email
-- verification, and team invitations.
--
-- The frontend already ships full UI for all of this (SignupPage,
-- ForgotPasswordPage, VerificationCodePage, ResetPasswordPage,
-- VerifyEmailPage, InvitationPage - see frontend/src/features/auth/) but
-- POST /auth/login was, until now, the only real endpoint behind any of it
-- - every other auth action only worked because the frontend's own
-- authApiMode defaults to a mock adapter. This migration is the data-model
-- half of closing that gap; routers/auth.py is the other half.
--
-- users.email_verified_at: nullable, NULL = not verified - a real column,
-- not a bolted-on flag, so RLS/every other query already scoped to `users`
-- can read it for free.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE;

-- One generic token table for password-reset, email-verification, and
-- team-invitation codes/links, discriminated by token_type - three near-
-- identical "generate a random code, hash it, expire it, consume it once"
-- flows, not three different data shapes. Never a tenant-scoped table (no
-- RLS): a password-reset/email-verification token belongs to a user, not a
-- tenant, and a team-invitation token is deliberately reachable by the
-- invited person BEFORE they have any tenant membership at all - the exact
-- same "structurally can't have tenant/user RLS context yet" bootstrap
-- problem migration 20260915020000_add_auth_lookup_functions.sql's own
-- docstring already describes for login. Only token_hash (never the real
-- code/token) is ever stored, so a leaked row in this table alone can't be
-- used to reset anyone's password or accept anyone's invitation.
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_type VARCHAR(30) NOT NULL CHECK (token_type IN ('PASSWORD_RESET', 'EMAIL_VERIFICATION', 'TEAM_INVITATION')),
    token_hash CHAR(64) NOT NULL,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    email VARCHAR(255),
    tenant_id UUID REFERENCES companies(tenant_id) ON DELETE CASCADE,
    role_key VARCHAR(50) REFERENCES system_roles(role_key),
    invited_by_user_id UUID REFERENCES users(user_id),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_auth_token_shape CHECK (
        (token_type IN ('PASSWORD_RESET', 'EMAIL_VERIFICATION') AND user_id IS NOT NULL)
        OR (token_type = 'TEAM_INVITATION' AND tenant_id IS NOT NULL AND email IS NOT NULL AND role_key IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_tokens_hash ON auth_tokens(token_hash);
-- Real lookup path every verify/consume call actually uses: type + hash,
-- only among tokens not yet spent - a used or long-expired token falling
-- out of this partial index is fine, expiry is still re-checked in code.
CREATE INDEX IF NOT EXISTS idx_auth_tokens_active_lookup ON auth_tokens(token_type, token_hash) WHERE used_at IS NULL;

-- Two narrow SECURITY DEFINER functions for the two real cases where a
-- pre-authentication (or acting-on-someone-else's-row) flow needs to write
-- to `users`, which RLS's own update_users_self policy otherwise restricts
-- to the row's own already-authenticated user_id (app.current_user_id) -
-- the identical bootstrap problem, and identical fix, migration
-- 20260915020000_add_auth_lookup_functions.sql's own docstring already
-- justifies for login's pre-auth email lookup. Both take an explicit
-- p_user_id (resolved beforehand from a verified token, never from
-- unauthenticated user input directly) rather than trusting current_setting -
-- there is no session context to trust at this point.
CREATE OR REPLACE FUNCTION auth_reset_password(p_user_id UUID, p_new_password_hash TEXT)
RETURNS VOID
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE users SET password_hash = p_new_password_hash, updated_at = NOW() WHERE user_id = p_user_id;
$$;
REVOKE ALL ON FUNCTION auth_reset_password(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_reset_password(UUID, TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION auth_mark_email_verified(p_user_id UUID)
RETURNS VOID
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE users SET email_verified_at = NOW(), updated_at = NOW() WHERE user_id = p_user_id AND email_verified_at IS NULL;
$$;
REVOKE ALL ON FUNCTION auth_mark_email_verified(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_mark_email_verified(UUID) TO ceopro_app;
