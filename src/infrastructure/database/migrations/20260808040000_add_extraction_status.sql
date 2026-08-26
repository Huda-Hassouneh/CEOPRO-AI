-- CEOPRO AI - Extraction pipeline status tracking.
-- extraction/pipeline.py needs a way to tell "not yet processed" apart from
-- "processed, genuinely zero entities found" for a news_record/social_mention
-- row - a LEFT JOIN against extracted_entity alone can't distinguish those two
-- cases. Mirrors rag_documents_metadata.processed_status's existing
-- Pending/Processed/Failed convention (spec S12: never silently drop
-- unprocessable data - a Failed row stays visible rather than disappearing).

ALTER TABLE news_record ADD COLUMN IF NOT EXISTS extraction_status VARCHAR(50) DEFAULT 'Pending';
ALTER TABLE social_mention ADD COLUMN IF NOT EXISTS extraction_status VARCHAR(50) DEFAULT 'Pending';
