-- CEOPRO AI - Restore document processing-status persistence to
-- rag_documents_metadata.
--
-- Found while implementing audit findings P0/P1 for src/ai/rag/: the whole
-- module's document lifecycle (rag/data_access.py::list_documents(status=...)/
-- mark_document_status(), rag/pipeline.py::ingest_pending_documents() marking
-- 'Pending' -> 'Processed'/'Failed') depends on a processed_status column that
-- does not exist anywhere in Final_schema.sql or any prior migration - not a
-- rename like the storage_bucket_path/minio_object_key mismatch fixed
-- alongside this, a genuinely missing column. Every call to
-- ingest_pending_documents() against the real schema would fail immediately
-- with UndefinedColumn, confirmed directly (not assumed) via a live disposable
-- Postgres before writing this migration.
--
-- Same three values rag/pipeline.py already writes: 'Pending' (the only
-- state a newly-uploaded/re-uploaded document should start in - default),
-- 'Processed', 'Failed'.

ALTER TABLE rag_documents_metadata
    ADD COLUMN IF NOT EXISTS processed_status VARCHAR(20) NOT NULL DEFAULT 'Pending';

ALTER TABLE rag_documents_metadata
    ADD CONSTRAINT chk_rag_doc_processed_status
    CHECK (processed_status IN ('Pending', 'Processed', 'Failed'));

CREATE INDEX IF NOT EXISTS idx_rag_documents_status_lookup
    ON rag_documents_metadata(tenant_id, processed_status);
