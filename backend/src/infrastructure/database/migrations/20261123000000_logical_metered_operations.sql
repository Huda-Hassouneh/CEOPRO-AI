-- One customer operation may have several independently accounted provider calls.
CREATE TABLE IF NOT EXISTS public.billing_logical_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    logical_operation_id TEXT NOT NULL CHECK (length(logical_operation_id) BETWEEN 1 AND 200),
    operation_kind TEXT NOT NULL CHECK (length(operation_kind) BETWEEN 1 AND 80),
    input_fingerprint TEXT NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','succeeded','failed','unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, logical_operation_id),
    UNIQUE (tenant_id, id)
);

ALTER TABLE public.billing_logical_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_logical_operations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS accounting_scope ON public.billing_logical_operations;
CREATE POLICY accounting_scope ON public.billing_logical_operations TO ceopro_credit_accounting
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
DROP POLICY IF EXISTS accounting_boundary ON public.billing_logical_operations;
CREATE POLICY accounting_boundary ON public.billing_logical_operations AS RESTRICTIVE TO ceopro_credit_accounting
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
REVOKE ALL ON public.billing_logical_operations FROM PUBLIC, ceopro_app;
GRANT SELECT, INSERT (tenant_id, logical_operation_id, operation_kind, input_fingerprint)
    ON public.billing_logical_operations TO ceopro_credit_accounting;
GRANT UPDATE (status, updated_at) ON public.billing_logical_operations TO ceopro_credit_accounting;

CREATE OR REPLACE FUNCTION public.billing_logical_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.logical_operation_id IS DISTINCT FROM OLD.logical_operation_id
       OR NEW.operation_kind IS DISTINCT FROM OLD.operation_kind
       OR NEW.input_fingerprint IS DISTINCT FROM OLD.input_fingerprint
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'logical operation identity is immutable';
    END IF;
    IF OLD.status <> 'in_progress' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'logical operation is already terminal';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS billing_logical_operation_guard ON public.billing_logical_operations;
CREATE TRIGGER billing_logical_operation_guard BEFORE UPDATE ON public.billing_logical_operations
    FOR EACH ROW EXECUTE FUNCTION public.billing_logical_operation_guard();

ALTER TABLE public.usage_ledger ADD COLUMN IF NOT EXISTS logical_operation_ref UUID;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.usage_ledger'::regclass
                   AND conname = 'usage_ledger_logical_operation_fk') THEN
        ALTER TABLE public.usage_ledger ADD CONSTRAINT usage_ledger_logical_operation_fk
            FOREIGN KEY (tenant_id, logical_operation_ref)
            REFERENCES public.billing_logical_operations (tenant_id, id);
    END IF;
END $$;
GRANT INSERT (logical_operation_ref) ON public.usage_ledger TO ceopro_credit_accounting;
CREATE INDEX IF NOT EXISTS usage_ledger_logical_operation_idx
    ON public.usage_ledger (tenant_id, logical_operation_ref) WHERE logical_operation_ref IS NOT NULL;

CREATE OR REPLACE FUNCTION public.billing_ledger_logical_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.logical_operation_ref IS DISTINCT FROM OLD.logical_operation_ref THEN
        RAISE EXCEPTION 'ledger logical operation reference is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS billing_ledger_logical_operation_guard ON public.usage_ledger;
CREATE TRIGGER billing_ledger_logical_operation_guard BEFORE UPDATE ON public.usage_ledger
    FOR EACH ROW EXECUTE FUNCTION public.billing_ledger_logical_operation_guard();
