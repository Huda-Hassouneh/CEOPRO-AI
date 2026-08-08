-- Originally created 8 duplicate RLS policies on tables init_schema.sql
-- already enables RLS and creates correct policies on. Found two real bugs
-- via end-to-end testing against the actual non-superuser ceopro_app role
-- (migrations/20260808020000_add_app_role_and_force_rls.sql) rather than
-- just reading the SQL:
--
--   1. Wrong table name (`ai_recommendations`, renamed to `evidence_records`
--      in commit 613ec53 before this migration was ever written) - fixed
--      2026-08-08, see PENDING_ACTIONS.md #21.
--   2. Worse: even after that fix, having BOTH this migration's policies and
--      init_schema.sql's own correct ones active on the same 8 tables broke
--      queries outright. This migration's policies call
--      current_setting('app.current_tenant_id') with no missing_ok
--      argument, which RAISES "unrecognized configuration parameter" for
--      any session that hasn't called SET app.current_tenant_id yet -
--      instead of init_schema.sql's own policies' safe
--      current_setting('app.current_tenant_id', true), which returns NULL
--      (so the row is correctly excluded, not an error). Postgres evaluates
--      all permissive policies on a table and a RAISE from any one of them
--      fails the whole query - confirmed directly: `SELECT COUNT(*) FROM
--      products;` as ceopro_app with no tenant context set threw this error
--      instead of the intended "zero rows."
--
-- Since init_schema.sql already correctly covers every table this migration
-- touches, the fix is to drop this migration's redundant, buggy policies
-- rather than patch their current_setting() calls - having the same
-- protection defined twice under two different names serves no purpose.
-- ALTER TABLE ... ENABLE ROW LEVEL SECURITY is left in as a harmless,
-- idempotent no-op (these tables already have RLS enabled) so this
-- migration's history stays legible without silently becoming an empty file.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_users ON users;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_products ON products;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_transactions ON transactions;
ALTER TABLE competitors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_competitors ON competitors;
ALTER TABLE competitor_prices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_competitor_prices ON competitor_prices;
ALTER TABLE demand_forecasts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_demand_forecasts ON demand_forecasts;
ALTER TABLE evidence_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_ai_recommendations ON evidence_records;
ALTER TABLE rag_documents_metadata ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_rag_documents_metadata ON rag_documents_metadata;
