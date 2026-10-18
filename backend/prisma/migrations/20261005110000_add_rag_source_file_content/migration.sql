-- The public Gradio RAG service processes documents per request and does not
-- retain uploads. CEOPRO stores the tenant-owned source bytes so later queries
-- can submit them again without relying on the external AI service.
ALTER TABLE rag_documents_metadata
  ADD COLUMN IF NOT EXISTS source_file_content BYTEA;
