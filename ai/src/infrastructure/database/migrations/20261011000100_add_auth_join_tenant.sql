-- Accepting a team invitation adds the invited person to the company.
-- tenant_users' policies can't allow that from the invitee's own connection:
-- get_current_tenant() only trusts people who are already active members,
-- and the onboarding policy only allows a company's first member. So the
-- insert runs here, after routers/auth.py has checked the invitation token
-- (unused, unexpired, for this company and role). An invitation for someone
-- who was removed earlier brings them back with the invited role.
CREATE OR REPLACE FUNCTION auth_join_tenant(p_tenant_id UUID, p_user_id UUID, p_role_key VARCHAR)
RETURNS VOID
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (p_tenant_id, p_user_id, p_role_key)
    ON CONFLICT (tenant_id, user_id) DO UPDATE
        SET role_key = EXCLUDED.role_key, removed_at = NULL, joined_at = CURRENT_TIMESTAMP
        WHERE tenant_users.removed_at IS NOT NULL;
$$;
REVOKE ALL ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR) TO ceopro_app;
