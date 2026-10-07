-- Prisma creates imported transactions with `RETURNING transaction_id` so the
-- worker can link each staging row to its committed transaction. PostgreSQL
-- requires SELECT privilege on returned columns, and RLS requires a SELECT
-- policy for rows returned by the INSERT.
GRANT SELECT (transaction_id)
    ON TABLE public.transactions
    TO ceopro_ingestion_worker;

DROP POLICY IF EXISTS ingestion_worker_transaction_return
    ON public.transactions;
CREATE POLICY ingestion_worker_transaction_return
    ON public.transactions
    FOR SELECT
    TO ceopro_ingestion_worker
    USING (
        sale_source = 'IMPORT'
        AND EXISTS (
            SELECT 1
            FROM public.companies c
            WHERE c.tenant_id = transactions.tenant_id
              AND c.business_type IS DISTINCT FROM 'platform'
              AND c.deleted_at IS NULL
              AND c.platform_status = 'active'
        )
    );
