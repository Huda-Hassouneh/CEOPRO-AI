-- CEOPRO AI - Pre-authentication lookup functions for POST /auth/login.
--
-- Real, structural gap this closes: Final_schema.sql's own RLS policy on
-- `users` (select_users_perimeter) requires the session to ALREADY have
-- either app.current_user_id set to the row being read, or
-- app.current_tenant_id set to a tenant that user belongs to. A login
-- request, by definition, has neither yet - it only has an email address -
-- so the restricted ceopro_app role genuinely cannot read `users` by email
-- through any combination of session GUCs. This is correct RLS behavior,
-- not a bug to route around by connecting as the superuser (ceopro_admin) -
-- see RED_FLAGS.md's own "ceopro_admin unconditionally bypasses RLS" entry
-- and main.py's docstring on exactly why that anti-pattern was fixed.
--
-- The standard, safe pattern for this exact bootstrap problem: a narrow,
-- auditable SECURITY DEFINER function that runs with the privileges of
-- its OWNER (whoever applies this migration, i.e. the real superuser),
-- not the caller - so ceopro_app can be granted EXECUTE on it without
-- ever being granted broader SELECT on `users`/`tenant_users` directly.
-- Each function returns only the specific columns a login flow actually
-- needs, nothing else.

CREATE OR REPLACE FUNCTION auth_lookup_user_by_email(p_email TEXT)
RETURNS TABLE(user_id UUID, password_hash TEXT, full_name VARCHAR, preferred_language VARCHAR)
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.user_id, u.password_hash, u.full_name, u.preferred_language
    FROM users u
    WHERE LOWER(u.email) = LOWER(p_email);
$$;

REVOKE ALL ON FUNCTION auth_lookup_user_by_email(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_user_by_email(TEXT) TO ceopro_app;

-- Same bootstrap problem, one step later: once a user is authenticated by
-- password, the login flow still needs to know WHICH tenant(s) they
-- belong to before app.current_tenant_id can be set for the very first
-- time this session - isolation_tenant_users' own policy (tenant_id =
-- get_current_tenant()) can't resolve that either, for the same reason.
CREATE OR REPLACE FUNCTION auth_lookup_user_memberships(p_user_id UUID)
RETURNS TABLE(tenant_id UUID, role_key VARCHAR, business_name VARCHAR)
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    SELECT tu.tenant_id, tu.role_key, c.business_name
    FROM tenant_users tu
    JOIN companies c ON c.tenant_id = tu.tenant_id
    WHERE tu.user_id = p_user_id AND tu.removed_at IS NULL AND c.deleted_at IS NULL
    ORDER BY tu.joined_at ASC;
$$;

REVOKE ALL ON FUNCTION auth_lookup_user_memberships(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_user_memberships(UUID) TO ceopro_app;
