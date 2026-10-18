-- Whether a user's email address is confirmed, for the sign-in endpoints
-- (routers/auth.py), which run before any tenant is known and so read users
-- only through SECURITY DEFINER functions like auth_lookup_user_by_email.
CREATE OR REPLACE FUNCTION auth_email_verified(p_user_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE((SELECT email_verified_at IS NOT NULL FROM users WHERE user_id = p_user_id), FALSE);
$$;
REVOKE ALL ON FUNCTION auth_email_verified(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_email_verified(UUID) TO ceopro_app;
