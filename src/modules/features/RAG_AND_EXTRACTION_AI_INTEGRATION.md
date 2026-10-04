# Feature/extraction AI integration

## Ownership after the RAG split

Knowledge Base / RAG transport is no longer owned by the shared `features` module.

Dedicated RAG ownership now lives in:

```text
src/modules/rag/
```

and exposes:

```text
GET  /features/rag/documents
POST /features/rag/documents
GET  /features/rag/chunks/:chunk_id
POST /features/rag/query
```

See:

```text
src/modules/rag/RAG_AI_INTEGRATION.md
```

for the upstream AI contract and mock/real connection instructions.

## Extraction flow retained here

The shared features module still contains the legacy/general extraction route:

```text
POST /features/extraction/upload
POST /features/extraction/process-pending
```

The Data Connection domain owns its separate business-data ingestion API and client. Knowledge Base uploads must not use `/features/extraction/upload`; they now use `/features/rag/documents` and upstream AI `POST /rag/documents`.
