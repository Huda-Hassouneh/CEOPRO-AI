-- Email verification before account creation.
-- Pending signup rows hold only a password hash and signup fields; users,
-- companies, memberships, and sessions are created only after confirmation.
CREATE TABLE pending_signups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name VARCHAR(150),
    preferred_language VARCHAR(5) NOT NULL DEFAULT 'en',
    business_name VARCHAR(255) NOT NULL,
    business_type VARCHAR(100),
    country_code VARCHAR(2) NOT NULL DEFAULT 'JO',
    primary_currency VARCHAR(3) NOT NULL DEFAULT 'JOD',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Amman',
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    last_email_sent_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pending_signups_expiry ON pending_signups (expires_at);

CREATE TABLE email_verification_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_email_verification_grants_expiry
    ON email_verification_grants (expires_at, consumed_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON pending_signups TO ceopro_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON email_verification_grants TO ceopro_app;
