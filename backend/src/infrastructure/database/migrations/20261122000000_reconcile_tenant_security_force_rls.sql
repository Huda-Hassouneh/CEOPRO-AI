-- Preserve main's tenant-security policies while satisfying KEEL's existing
-- FORCE RLS invariant. Do not add these tenant tables to owner-bypass exceptions.
-- Authentication keeps its existing app.auth_lookup scope; model rows retain
-- their existing tenant identity. No policy, grant or customer data is changed.
ALTER TABLE public.auth_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE public.model_versions FORCE ROW LEVEL SECURITY;
