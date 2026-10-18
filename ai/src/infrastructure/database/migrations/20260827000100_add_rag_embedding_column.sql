-- CEOPRO AI - Restore vector-search persistence to rag_document_chunks.
-- Final_schema.sql creates no extensions at all and rag_document_chunks has
-- no embedding column whatsoever - semantic (FAISS/pgvector) retrieval has
-- nowhere to persist to. Sized at 384, not a round-number guess: the actual
-- model in production use (src/ai/rag/embeddings.py, RAG_EMBEDDING_MODEL
-- default sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
-- outputs 384-dimension vectors - confirmed against the model's own config,
-- not assumed.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE rag_document_chunks ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE rag_document_chunks ADD COLUMN IF NOT EXISTS embedding_model_version VARCHAR(100);
