CREATE TABLE IF NOT EXISTS public.rag_search_execution_receipts (
    tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    cache_fingerprint text NOT NULL CHECK (cache_fingerprint ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('preparing', 'provider_started', 'succeeded')),
    owner_token uuid NOT NULL,
    lease_expires_at timestamptz,
    provider text,
    result_json jsonb,
    result_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, cache_fingerprint),
    CHECK ((state = 'preparing') = (lease_expires_at IS NOT NULL)),
    CHECK ((state = 'succeeded') = (result_json IS NOT NULL AND result_expires_at IS NOT NULL AND provider IS NOT NULL))
);
ALTER TABLE public.rag_search_execution_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_search_execution_receipts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rag_search_receipt_tenant ON public.rag_search_execution_receipts;
CREATE POLICY rag_search_receipt_tenant ON public.rag_search_execution_receipts TO ceopro_app
    USING (tenant_id = public.get_current_tenant())
    WITH CHECK (tenant_id = public.get_current_tenant());
REVOKE ALL ON public.rag_search_execution_receipts FROM PUBLIC, ceopro_app;
GRANT SELECT, INSERT (tenant_id, cache_fingerprint, state, owner_token, lease_expires_at),
    UPDATE (state, owner_token, lease_expires_at, provider, result_json, result_expires_at, updated_at)
    ON public.rag_search_execution_receipts TO ceopro_app;

CREATE OR REPLACE FUNCTION public.rag_search_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.cache_fingerprint IS DISTINCT FROM OLD.cache_fingerprint
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'search receipt identity is immutable';
    END IF;
    IF OLD.state = 'provider_started' AND (NEW.state <> 'succeeded' OR NEW.owner_token <> OLD.owner_token) THEN
        RAISE EXCEPTION 'started search cannot be retried automatically';
    END IF;
    IF OLD.state = 'succeeded' AND (NEW.state <> 'preparing' OR OLD.result_expires_at > now()) THEN
        RAISE EXCEPTION 'fresh search result cannot be replaced';
    END IF;
    IF OLD.state = 'preparing' AND NEW.owner_token <> OLD.owner_token AND OLD.lease_expires_at > now() THEN
        RAISE EXCEPTION 'active search preparation cannot be taken over';
    END IF;
    IF OLD.state = 'preparing' AND NEW.state = 'provider_started'
       AND (NEW.owner_token <> OLD.owner_token OR OLD.lease_expires_at <= now()) THEN
        RAISE EXCEPTION 'expired search preparation cannot start provider work';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS rag_search_receipt_guard ON public.rag_search_execution_receipts;
CREATE TRIGGER rag_search_receipt_guard BEFORE UPDATE ON public.rag_search_execution_receipts
    FOR EACH ROW EXECUTE FUNCTION public.rag_search_receipt_guard();
