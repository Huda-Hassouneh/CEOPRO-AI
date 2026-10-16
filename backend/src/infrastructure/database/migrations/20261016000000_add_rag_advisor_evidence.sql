-- KEEL assistant: evidence-linked answers. Additive only.

-- The page a document passage came from (PDFs), shown in its reference.
ALTER TABLE rag_document_chunks ADD COLUMN IF NOT EXISTS page_number INT;

-- What a conversation is about (products, countries, period, quantity,
-- currency...), so a follow-up keeps it; and each answer's claims,
-- references and calculations, so a reopened conversation shows them.
ALTER TABLE conversation_sessions ADD COLUMN IF NOT EXISTS state JSONB;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS answer_payload JSONB;

-- Public web pages read during research, cached so the same page is not
-- fetched again for every question. Public content only: no company id,
-- no question text and nothing about who asked is stored here.
CREATE TABLE IF NOT EXISTS research_pages (
    url TEXT PRIMARY KEY,
    status VARCHAR(40) NOT NULL,
    final_url TEXT,
    title TEXT,
    site_name VARCHAR(200),
    published_at VARCHAR(40),
    modified_at VARCHAR(40),
    language VARCHAR(20),
    page_text TEXT,
    content_hash VARCHAR(64),
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_research_pages_fetched_at ON research_pages (fetched_at);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON research_pages TO ceopro_app;
    END IF;
END $$;
