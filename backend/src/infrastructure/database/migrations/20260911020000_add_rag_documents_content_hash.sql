-- CEOPRO AI - content_hash on rag_documents_metadata, closing a real
-- performance gap found in the production-hardening audit.
--
-- structured_summaries.py::regenerate_all_structured_summaries() runs on
-- every market.analysis.requested event (i.e. after every scrape that
-- persists new reviews), unconditionally re-uploading and re-embedding
-- all four summary slots even when a given slot's generated text is
-- byte-identical to what's already there (e.g. only sentiment changed
-- this run - sales history, competitor landscape, and market pricing
-- text can easily be unchanged). Every regeneration flipped
-- processed_status back to 'Pending', triggering a real, avoidable
-- MinIO PUT + full re-chunk/re-embed cycle for content that didn't
-- change at all.
--
-- Nullable and NOT backfilled: an existing row with no stored hash yet
-- simply regenerates once more (correct, safe default - never silently
-- treated as "unchanged" without real evidence) and gets a real hash
-- from that point on.
ALTER TABLE rag_documents_metadata
    ADD COLUMN IF NOT EXISTS content_hash TEXT;
