-- CEOPRO AI - Field-level ingestion validation support.
--
-- Product requirement: a compliant-template row must not be rejected in
-- full because one field failed semantic validation (e.g. a negative
-- price) - the other, valid fields must still be extracted. The
-- extraction pipeline (src/ai/extraction/ingestion_pipeline.py) now
-- tracks this at field granularity and needs a row-level status distinct
-- from VALID/INVALID for "processed, but one or more fields were dropped" -
-- import_staging_rows.validation_status's CHECK constraint only allowed
-- PENDING/VALID/INVALID/COMMITTED, with no such value. Extends it rather
-- than overloading an existing status, per this session's own established
-- "extend, don't reduce" precedent.
--
-- validation_errors stays TEXT (no type change) - a JSON-encoded
-- {field: message} dict is written into it for a PARTIAL row (or for an
-- INVALID row a plain string reason), same column, no migration needed
-- for that part since TEXT already holds any string.

ALTER TABLE import_staging_rows DROP CONSTRAINT IF EXISTS chk_staging_status;
ALTER TABLE import_staging_rows ADD CONSTRAINT chk_staging_status
    CHECK (validation_status IN ('PENDING', 'VALID', 'PARTIAL', 'INVALID', 'COMMITTED'));

-- 'transactions' (migrations/20260830000000_add_transactions_and_model_
-- versions.sql, same session) didn't exist yet when chk_committed_table_
-- guard was first defined - a sales-transaction import (this pipeline's
-- own canonical template, template_contract.py) has nowhere valid to
-- commit to without this.
ALTER TABLE import_staging_rows DROP CONSTRAINT IF EXISTS chk_committed_table_guard;
ALTER TABLE import_staging_rows ADD CONSTRAINT chk_committed_table_guard
    CHECK (committed_table IN ('products', 'inventory', 'invoices', 'invoice_items', 'reviews', 'transactions'));

-- Job-level aggregate to match the new row-level status, so a caller can
-- see "how many rows in this job needed a field dropped" without querying
-- import_staging_rows directly.
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS rows_partial INT DEFAULT 0;
