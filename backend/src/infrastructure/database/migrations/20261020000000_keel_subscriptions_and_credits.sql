-- KEEL subscriptions: Standard / Plus / Pro / Custom, Data Credits and AI
-- Credits, report and seat limits, and an auditable usage ledger
-- (docs/SUBSCRIPTIONS_AND_CREDITS.md).
--
-- Plan keys stay starter / growth / enterprise / custom: Stripe prices,
-- live subscriptions and webhooks already resolve to them, so only the names
-- customers see change. The retired 2026 'standard' and 'pro' packages keep
-- their keys (old Stripe prices still resolve to them) under legacy names.
--
--                        Standard   Plus    Pro     Custom
--   monthly price (USD)        55    140    350     quoted
--   free trial (days)          14     14      7     per contract
--   products                  100    250    750     contract
--   reports / month             5     20     60     contract
--   team seats                  5     20     60     contract
--   competitors            budget-based (Data Credits), no fixed count
--   Data / AI Credits      see scripts/billing_cost_model.py; the numbers
--                          below are that model's conservative output
--
-- Credits are customer-facing units; money stays in USD columns. Provider
-- prices are never invented here: AI model prices and paid data-provider
-- prices start unconfigured, and an unconfigured price blocks that paid
-- operation (fail closed) until an operator records the real price with
-- scripts/billing_admin.py. Only providers that charge nothing (public open
-- data and self-hosted services) are seeded, at zero.
--
-- Undo: rollback/20261020000000_keel_subscriptions_and_credits.down.sql

-- --- Plans ------------------------------------------------------------------

UPDATE usage_plans SET display_name = 'Standard', display_name_ar = 'القياسية', monthly_price = 55, trial_days = 14,
    tier_level = 1, self_serve = TRUE, is_active = TRUE, catalog_version = 'keel-2026-10-credits' WHERE plan_key = 'starter';
UPDATE usage_plans SET display_name = 'Plus', display_name_ar = 'بلس', monthly_price = 140, trial_days = 14,
    tier_level = 2, self_serve = TRUE, is_active = TRUE, catalog_version = 'keel-2026-10-credits' WHERE plan_key = 'growth';
UPDATE usage_plans SET display_name = 'Pro', display_name_ar = 'برو', monthly_price = 350, trial_days = 7,
    tier_level = 3, self_serve = TRUE, is_active = TRUE, catalog_version = 'keel-2026-10-credits' WHERE plan_key = 'enterprise';
UPDATE usage_plans SET display_name = 'Custom', display_name_ar = 'المخصصة', monthly_price = NULL, trial_days = 0,
    tier_level = 4, self_serve = FALSE, is_active = TRUE, catalog_version = 'keel-2026-10-credits' WHERE plan_key = 'custom';
UPDATE usage_plans SET display_name = 'Legacy Standard (2026)', display_name_ar = 'القياسية السابقة (2026)' WHERE plan_key = 'standard';
UPDATE usage_plans SET display_name = 'Legacy Pro (2026)', display_name_ar = 'الاحترافية السابقة (2026)' WHERE plan_key = 'pro';

-- --- New metered features ----------------------------------------------------

INSERT INTO usage_features (feature_code, unit, aggregation_type, reset_cycle) VALUES
    ('monthly_reports', 'reports', 'sum', 'billing_period'),
    ('team_seats', 'seats', 'max', 'lifetime'),
    ('data_credits', 'credits', 'sum', 'billing_period'),
    ('ai_credits', 'credits', 'sum', 'billing_period')
ON CONFLICT (feature_code) DO NOTHING;

-- A trial can have its own, smaller allowance (NULL = the plan's limit).
ALTER TABLE usage_plan_limits ADD COLUMN IF NOT EXISTS trial_limit_value BIGINT
    CHECK (trial_limit_value IS NULL OR trial_limit_value >= 0);

-- Credit budgets: the monthly figure and the bounded trial figure come from
-- scripts/billing_cost_model.py (test_billing_cost_model checks they match).
INSERT INTO usage_plan_limits (plan_key, feature_code, limit_value, trial_limit_value) VALUES
    ('starter', 'tracked_products', 100, NULL), ('growth', 'tracked_products', 250, NULL), ('enterprise', 'tracked_products', 750, NULL),
    ('starter', 'monthly_reports', 5, NULL), ('growth', 'monthly_reports', 20, NULL), ('enterprise', 'monthly_reports', 60, NULL),
    ('starter', 'team_seats', 5, NULL), ('growth', 'team_seats', 20, NULL), ('enterprise', 'team_seats', 60, NULL),
    ('starter', 'data_credits', 436, 43), ('growth', 'data_credits', 1111, 111), ('enterprise', 'data_credits', 2780, 278),
    ('starter', 'ai_credits', 436, 43), ('growth', 'ai_credits', 1111, 111), ('enterprise', 'ai_credits', 2780, 278),
    -- Custom: the Pro plan's finite budgets until an approved contract sets
    -- the company's own (tenant_entitlement_overrides). Never unlimited.
    ('custom', 'monthly_reports', 60, NULL), ('custom', 'team_seats', 60, NULL),
    ('custom', 'data_credits', 2780, 278), ('custom', 'ai_credits', 2780, 278),
    -- Retired packages keep working for anyone still on them, with the
    -- nearest current plan's report, seat and credit terms.
    ('standard', 'monthly_reports', 5, NULL), ('standard', 'team_seats', 5, NULL),
    ('standard', 'data_credits', 436, 43), ('standard', 'ai_credits', 436, 43),
    ('pro', 'monthly_reports', 20, NULL), ('pro', 'team_seats', 20, NULL),
    ('pro', 'data_credits', 1111, 111), ('pro', 'ai_credits', 1111, 111)
ON CONFLICT (plan_key, feature_code) DO UPDATE
    SET limit_value = EXCLUDED.limit_value, trial_limit_value = EXCLUDED.trial_limit_value;

-- Competitors are no longer a fixed count: discovery and monitoring are
-- limited by the Data Credit budget instead.
-- Companies already on Custom keep their earlier limits until an operator
-- records their contract.
UPDATE usage_plan_limits SET limit_value = NULL
WHERE feature_code = 'tracked_competitors' AND plan_key IN ('starter', 'growth', 'enterprise', 'custom');

-- --- Cost policy (one row) ----------------------------------------------------

CREATE TABLE IF NOT EXISTS billing_cost_policy (
    policy_id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (policy_id),
    credit_usd_value NUMERIC(12, 6) NOT NULL CHECK (credit_usd_value > 0),
    target_contribution_margin NUMERIC(5, 4) NOT NULL CHECK (target_contribution_margin >= 0 AND target_contribution_margin < 1),
    default_safety_margin NUMERIC(5, 4) NOT NULL CHECK (default_safety_margin >= 0 AND default_safety_margin <= 2),
    warning_thresholds INT[] NOT NULL,
    max_ai_concurrency INT NOT NULL CHECK (max_ai_concurrency > 0),
    max_ai_input_tokens INT NOT NULL CHECK (max_ai_input_tokens > 0),
    max_ai_output_tokens INT NOT NULL CHECK (max_ai_output_tokens > 0),
    reservation_timeout_seconds INT NOT NULL CHECK (reservation_timeout_seconds > 0),
    top_ups_enabled BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT top_ups_enabled),
    ai_fallback_policy VARCHAR(20) NOT NULL DEFAULT 'none' CHECK (ai_fallback_policy IN ('none')),
    updated_by VARCHAR(200) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO billing_cost_policy (credit_usd_value, target_contribution_margin, default_safety_margin, warning_thresholds,
                                 max_ai_concurrency, max_ai_input_tokens, max_ai_output_tokens, reservation_timeout_seconds,
                                 updated_by)
VALUES (0.01, 0.70, 0.15, ARRAY[70, 85, 100], 3, 24000, 4000, 900, 'migration 20261020000000')
ON CONFLICT (policy_id) DO NOTHING;

-- --- Provider cost schedules -------------------------------------------------
-- One row per (budget, provider, operation, billable unit). unit_cost_usd
-- NULL = the real price isn't known yet -> the operation is refused.

CREATE TABLE IF NOT EXISTS provider_cost_schedules (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data', 'ai')),
    provider VARCHAR(60) NOT NULL,
    operation VARCHAR(120) NOT NULL,
    unit VARCHAR(30) NOT NULL CHECK (unit IN ('request', 'record', 'page', 'input_token', 'output_token',
                                              'cache_read_token', 'cache_write_token', 'image')),
    unit_cost_usd NUMERIC(20, 12) CHECK (unit_cost_usd IS NULL OR unit_cost_usd >= 0),
    safety_margin NUMERIC(5, 4) CHECK (safety_margin IS NULL OR (safety_margin >= 0 AND safety_margin <= 2)),
    charged_on_failure BOOLEAN NOT NULL DEFAULT TRUE,
    cost_is_final BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL,
    verified_at DATE,
    configured_by VARCHAR(200) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (budget_kind, provider, operation, unit)
);

INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin, charged_on_failure,
                                     source, configured_by) VALUES
    ('data', 'openstreetmap', 'overpass_query', 'request', 0, 0, FALSE, 'Public Overpass API, no charge', 'migration 20261020000000'),
    ('data', 'nominatim', 'search', 'request', 0, 0, FALSE, 'Public OpenStreetMap Nominatim, no charge', 'migration 20261020000000'),
    ('data', 'photon', 'search', 'request', 0, 0, FALSE, 'Public Komoot Photon, no charge', 'migration 20261020000000'),
    ('data', 'wikidata', 'sparql_query', 'request', 0, 0, FALSE, 'Public Wikidata Query Service, no charge', 'migration 20261020000000'),
    ('data', 'overture', 'public_dataset_read', 'request', 0, 0, FALSE, 'Overture Maps public dataset (open data), no charge', 'migration 20261020000000'),
    ('data', 'searxng', 'search', 'request', 0, 0, FALSE, 'Self-hosted SearXNG: no provider charge (hosting is infrastructure)', 'migration 20261020000000'),
    -- Paid providers: rows exist so operators see what must be priced; NULL until confirmed.
    ('data', 'google_places', 'text_search', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Google Maps Platform bill', 'migration 20261020000000'),
    ('data', 'google_cse', 'search', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Google Programmable Search bill', 'migration 20261020000000'),
    ('data', 'apify', 'actor_run', 'record', NULL, NULL, TRUE, 'Price not confirmed - set from the Apify actor pricing', 'migration 20261020000000'),
    ('data', 'gdelt', 'doc_search', 'request', 0, 0, FALSE, 'Public GDELT DOC API, no charge', 'migration 20261020000000'),
    ('data', 'google_geocoding', 'geocode', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Google Maps Platform bill', 'migration 20261020000000'),
    ('data', 'brave_search', 'search', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Brave Search API plan', 'migration 20261020000000'),
    ('data', 'tavily', 'search', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Tavily plan', 'migration 20261020000000'),
    ('ai', 'huggingface', 'image_generation', 'image', NULL, NULL, TRUE, 'Price not confirmed - set from the Hugging Face Inference bill', 'migration 20261020000000'),
    ('ai', 'cloudflare', 'image_generation', 'image', NULL, NULL, TRUE, 'Price not confirmed - set from the Cloudflare Workers AI bill', 'migration 20261020000000'),
    ('ai', 'pollinations', 'image_generation', 'image', 0, 0, FALSE, 'Keyless public Pollinations endpoint, no charge', 'migration 20261020000000'),
    ('ai', 'local', '*', 'input_token', 0, 0, FALSE, 'Self-hosted llama-server: no provider charge', 'migration 20261020000000'),
    ('ai', 'local', '*', 'output_token', 0, 0, FALSE, 'Self-hosted llama-server: no provider charge', 'migration 20261020000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;
-- Apify bills a run after it finishes: its calls are charged with a margin and reconciled.
UPDATE provider_cost_schedules SET cost_is_final = FALSE WHERE provider = 'apify';

-- --- Spending caps and kill switches -----------------------------------------
-- provider '*' is the global switch. monthly_cap_usd NULL = no platform cap.

CREATE TABLE IF NOT EXISTS provider_spend_controls (
    provider VARCHAR(60) PRIMARY KEY,
    monthly_cap_usd NUMERIC(14, 4) CHECK (monthly_cap_usd IS NULL OR monthly_cap_usd >= 0),
    kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    updated_by VARCHAR(200) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO provider_spend_controls (provider, kill_switch, reason, updated_by)
VALUES ('*', FALSE, 'Global switch for every paid provider', 'migration 20261020000000')
ON CONFLICT (provider) DO NOTHING;

-- --- Credit balances -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenant_credit_balances (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data', 'ai')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    reserved_credits NUMERIC(16, 4) NOT NULL DEFAULT 0 CHECK (reserved_credits >= 0),
    consumed_credits NUMERIC(16, 4) NOT NULL DEFAULT 0 CHECK (consumed_credits >= 0),
    consumed_cost_usd NUMERIC(16, 6) NOT NULL DEFAULT 0 CHECK (consumed_cost_usd >= 0),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, budget_kind, period_start)
);

-- --- Usage ledger ------------------------------------------------------------
-- One row per billable provider call (or per metered operation step). A row
-- is written 'reserved' before the call and settled exactly once; after that
-- only reconciliation can move it, and corrections are separate adjustment
-- rows. The (tenant_id, idempotency_key) pair can never charge twice.

CREATE TABLE IF NOT EXISTS usage_ledger (
    ledger_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    subscription_id UUID,
    plan_key VARCHAR(50) NOT NULL,
    plan_status VARCHAR(30) NOT NULL,
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data', 'ai')),
    period_start DATE NOT NULL,
    operation_id UUID NOT NULL,
    operation_type VARCHAR(80) NOT NULL,
    usage_class VARCHAR(40),
    provider VARCHAR(60) NOT NULL,
    provider_operation VARCHAR(120) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL CHECK (status IN ('reserved', 'consumed', 'released', 'failed_charged',
                                                  'pending_reconciliation', 'reconciled')),
    estimated_units JSONB NOT NULL DEFAULT '{}'::jsonb,
    measured_units JSONB,
    estimated_cost_usd NUMERIC(16, 8) NOT NULL CHECK (estimated_cost_usd >= 0),
    actual_cost_usd NUMERIC(16, 8) CHECK (actual_cost_usd IS NULL OR actual_cost_usd >= 0),
    reserved_credits NUMERIC(16, 4) NOT NULL CHECK (reserved_credits >= 0),
    consumed_credits NUMERIC(16, 4) CHECK (consumed_credits IS NULL OR consumed_credits >= 0),
    provider_request_id VARCHAR(200),
    error_code VARCHAR(80),
    actor_user_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    settled_at TIMESTAMP WITH TIME ZONE,
    reconciled_at TIMESTAMP WITH TIME ZONE,
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_tenant_period ON usage_ledger (tenant_id, budget_kind, period_start, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_open ON usage_ledger (status, created_at) WHERE status IN ('reserved', 'pending_reconciliation');
CREATE INDEX IF NOT EXISTS idx_usage_ledger_provider_month ON usage_ledger (provider, created_at);

-- Financial corrections (reconciliation differences, operator credits):
-- append-only, never updated or deleted while the company exists.
CREATE TABLE IF NOT EXISTS usage_ledger_adjustments (
    adjustment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    ledger_id UUID REFERENCES usage_ledger(ledger_id) ON DELETE CASCADE,
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data', 'ai')),
    period_start DATE NOT NULL,
    credits_delta NUMERIC(16, 4) NOT NULL,
    cost_delta_usd NUMERIC(16, 8) NOT NULL DEFAULT 0,
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('reconciliation', 'admin_credit', 'admin_debit')),
    reference VARCHAR(200) NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(200) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, reference)
);

-- Ledger rows move forward only: reserved -> settled once, and only a
-- pending_reconciliation row can be reconciled. Money columns of a settled
-- row never change; deletes happen only when the company itself is deleted.
CREATE OR REPLACE FUNCTION usage_ledger_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM companies WHERE tenant_id = OLD.tenant_id) THEN
            RAISE EXCEPTION 'usage_ledger rows are immutable';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.tenant_id <> OLD.tenant_id OR NEW.idempotency_key <> OLD.idempotency_key
       OR NEW.estimated_cost_usd <> OLD.estimated_cost_usd OR NEW.reserved_credits <> OLD.reserved_credits
       OR NEW.budget_kind <> OLD.budget_kind OR NEW.period_start <> OLD.period_start THEN
        RAISE EXCEPTION 'usage_ledger reservation fields are immutable';
    END IF;
    IF OLD.status = 'reserved' THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'pending_reconciliation' AND NEW.status = 'reconciled'
       AND NEW.consumed_credits IS NOT DISTINCT FROM OLD.consumed_credits THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'usage_ledger row % is already settled (%)', OLD.ledger_id, OLD.status;
END $$;
DROP TRIGGER IF EXISTS trg_usage_ledger_guard ON usage_ledger;
CREATE TRIGGER trg_usage_ledger_guard BEFORE UPDATE OR DELETE ON usage_ledger
    FOR EACH ROW EXECUTE FUNCTION usage_ledger_guard();

CREATE OR REPLACE FUNCTION append_only_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM companies WHERE tenant_id = OLD.tenant_id) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END $$;
DROP TRIGGER IF EXISTS trg_usage_ledger_adjustments_guard ON usage_ledger_adjustments;
CREATE TRIGGER trg_usage_ledger_adjustments_guard BEFORE UPDATE OR DELETE ON usage_ledger_adjustments
    FOR EACH ROW EXECUTE FUNCTION append_only_guard();

-- --- Idempotent metered requests (reports and other counted actions) ---------

CREATE TABLE IF NOT EXISTS metered_request_keys (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    feature_code VARCHAR(60) NOT NULL REFERENCES usage_features(feature_code),
    idempotency_key VARCHAR(200) NOT NULL,
    period_start DATE NOT NULL,
    actor_user_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, feature_code, idempotency_key)
);

-- --- Custom contracts --------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenant_custom_contracts (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    contract_ref VARCHAR(120) NOT NULL,
    monthly_price NUMERIC(12, 2) CHECK (monthly_price IS NULL OR monthly_price >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    trial_days INT NOT NULL DEFAULT 0 CHECK (trial_days BETWEEN 0 AND 90),
    data_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    refresh_frequency VARCHAR(20) CHECK (refresh_frequency IS NULL OR refresh_frequency IN ('hourly', 'daily', 'weekly')),
    support_level VARCHAR(40),
    approved_by VARCHAR(200) NOT NULL,
    reason TEXT NOT NULL,
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Approved per-company limits; they replace the plan's limit for that feature.
CREATE TABLE IF NOT EXISTS tenant_entitlement_overrides (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    feature_code VARCHAR(60) NOT NULL REFERENCES usage_features(feature_code),
    limit_value BIGINT NOT NULL CHECK (limit_value >= 0),
    contract_ref VARCHAR(120) NOT NULL,
    approved_by VARCHAR(200) NOT NULL,
    reason TEXT NOT NULL,
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, feature_code)
);

CREATE TABLE IF NOT EXISTS entitlement_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES companies(tenant_id) ON DELETE CASCADE,
    action VARCHAR(40) NOT NULL,
    subject VARCHAR(120) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    contract_ref VARCHAR(120),
    approved_by VARCHAR(200) NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE OR REPLACE FUNCTION entitlement_audit_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND (OLD.tenant_id IS NULL OR EXISTS (SELECT 1 FROM companies WHERE tenant_id = OLD.tenant_id)) THEN
        RAISE EXCEPTION 'entitlement_audit_log is append-only';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'entitlement_audit_log is append-only';
    END IF;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS trg_entitlement_audit_guard ON entitlement_audit_log;
CREATE TRIGGER trg_entitlement_audit_guard BEFORE UPDATE OR DELETE ON entitlement_audit_log
    FOR EACH ROW EXECUTE FUNCTION entitlement_audit_guard();

-- --- Trials ------------------------------------------------------------------
-- Who started the trial, so one person can't collect a trial per new company.

ALTER TABLE billing_trials ADD COLUMN IF NOT EXISTS started_by_user_id UUID;
CREATE INDEX IF NOT EXISTS idx_billing_trials_started_by ON billing_trials (started_by_user_id) WHERE started_by_user_id IS NOT NULL;
-- A trial's expiry is its exact UTC timestamp (billing_trials.ends_at), not a date.
ALTER TABLE billing_trials ADD COLUMN IF NOT EXISTS expiry_notified_at TIMESTAMP WITH TIME ZONE;

-- --- Seats: joining checks the seat limit under a per-company lock ------------

DROP FUNCTION IF EXISTS auth_join_tenant(UUID, UUID, VARCHAR);
CREATE OR REPLACE FUNCTION auth_join_tenant(p_tenant_id UUID, p_user_id UUID, p_role_key VARCHAR, p_seat_limit BIGINT)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_members BIGINT;
BEGIN
    -- Serialises joins for one company so two acceptances can't both take the last seat.
    PERFORM pg_advisory_xact_lock(hashtextextended('keel_seats:' || p_tenant_id::text, 0));
    IF EXISTS (SELECT 1 FROM tenant_users WHERE tenant_id = p_tenant_id AND user_id = p_user_id AND removed_at IS NULL) THEN
        RETURN TRUE;  -- already a member; takes no new seat
    END IF;
    SELECT COUNT(*) INTO v_members FROM tenant_users WHERE tenant_id = p_tenant_id AND removed_at IS NULL;
    IF p_seat_limit IS NOT NULL AND v_members >= p_seat_limit THEN
        RETURN FALSE;
    END IF;
    INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (p_tenant_id, p_user_id, p_role_key)
    ON CONFLICT (tenant_id, user_id) DO UPDATE
        SET role_key = EXCLUDED.role_key, removed_at = NULL, joined_at = CURRENT_TIMESTAMP
        WHERE tenant_users.removed_at IS NOT NULL;
    RETURN TRUE;
END $$;
REVOKE ALL ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR, BIGINT) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR, BIGINT) TO ceopro_app;
    END IF;
END $$;

-- --- Row-level security and grants -------------------------------------------
-- Companies read their own balances, ledger, overrides and contract; every
-- write goes through the billing service's trusted connection.

ALTER TABLE tenant_credit_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_credit_balances FORCE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger FORCE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger_adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger_adjustments FORCE ROW LEVEL SECURITY;
ALTER TABLE metered_request_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE metered_request_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE tenant_custom_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_custom_contracts FORCE ROW LEVEL SECURITY;
ALTER TABLE tenant_entitlement_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_entitlement_overrides FORCE ROW LEVEL SECURITY;
ALTER TABLE entitlement_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE entitlement_audit_log FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['tenant_credit_balances', 'usage_ledger', 'usage_ledger_adjustments', 'metered_request_keys',
                               'tenant_custom_contracts', 'tenant_entitlement_overrides'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = tbl AND policyname = 'isolation_' || tbl) THEN
            EXECUTE format('CREATE POLICY %I ON %I FOR SELECT USING (tenant_id = get_current_tenant())', 'isolation_' || tbl, tbl);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON tenant_credit_balances, usage_ledger, usage_ledger_adjustments, metered_request_keys,
                      tenant_custom_contracts, tenant_entitlement_overrides, entitlement_audit_log,
                      billing_cost_policy, provider_cost_schedules, provider_spend_controls FROM ceopro_app;
        GRANT SELECT ON tenant_credit_balances, usage_ledger, usage_ledger_adjustments, metered_request_keys,
                        tenant_custom_contracts, tenant_entitlement_overrides, billing_cost_policy TO ceopro_app;
        -- Usage counters were app-writable; reports now go through metered_request_keys
        -- and the billing service, but other features still meter through them.
    END IF;
END $$;
