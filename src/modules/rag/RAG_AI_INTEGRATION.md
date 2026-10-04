# CEOPRO RAG document upload and AI integration

## Purpose

This module separates Knowledge Base / RAG documents from Connected Data ingestion.

The two flows are intentionally different:

```text
Knowledge Base / RAG
POST /features/rag/documents
        -> CEOPRO backend
        -> POST {AI_SERVICE_URL}/rag/documents

Connected Data / business ingestion
POST /data-connection
        -> CEOPRO backend
        -> extraction/business-ingestion pipeline
```

`/extraction/upload` must not be used as the Knowledge Base upload contract anymore.

## Folder structure

```text
src/modules/rag/
├── route/
│   └── rag.route.ts
├── controller/
│   └── rag.controller.ts
├── service/
│   └── rag.service.ts
├── repo/
│   └── rag.repo.ts
├── client/
│   └── rag.client.ts
├── types/
│   └── rag.types.ts
├── README.md
└── RAG_AI_INTEGRATION.md
```

The public CEOPRO paths are preserved:

- `GET /features/rag/documents`
- `POST /features/rag/documents`
- `GET /features/rag/chunks/:chunk_id`
- `POST /features/rag/query`

## AI document-upload contract

Upstream AI endpoint:

```http
POST /rag/documents
Authorization: Bearer <JWT>
Content-Type: multipart/form-data
```

Multipart field:

```text
file
```

Supported formats:

```text
.txt
.md
.pdf
.docx
.xlsx
```

Expected AI response:

```json
{
  "document_id": "uuid",
  "file_name": "document.pdf",
  "processed_status": "Pending"
}
```

The backend validates the returned `document_id`, `file_name`, and `processed_status` before accepting the response.

## Mock mode

RAG AI calls are mocked by default.

Default behavior:

```env
RAG_AI_USE_MOCKS=true
```

The code behaves as if that value is `true` even when the variable is absent.

Mock upload returns the same documented shape:

```json
{
  "document_id": "generated UUID",
  "file_name": "uploaded filename",
  "processed_status": "Pending"
}
```

This lets the frontend/backend flow work before the real AI service is connected.

## Connecting to the real AI service

Set:

```env
AI_SERVICE_URL=http://localhost:8000
RAG_AI_USE_MOCKS=false
```

For production, `AI_SERVICE_URL` should point to the deployed CEOPRO AI API over the private/service network or approved HTTPS endpoint.

No code change is required when switching from mock to real AI mode.

The backend forwards the incoming customer Bearer JWT to the AI service:

```http
Authorization: Bearer <same CEOPRO JWT>
```

The client then sends the uploaded binary as multipart field `file` to:

```text
{AI_SERVICE_URL}/rag/documents
```

## Backend responsibilities

Before calling AI, CEOPRO still owns:

- authentication;
- tenant resolution;
- `document_extraction` entitlement enforcement;
- remaining extraction quota;
- `document_storage_mb` capacity;
- maximum upload size;
- allowed extension validation.

After a successful AI response, CEOPRO:

1. stores the returned AI `document_id` in `rag_documents_metadata`;
2. stores the uploaded file size/content type/uploader/processing status;
3. increments `document_extraction` usage in KB;
4. returns only the documented RAG upload response to the frontend.

The current database requires `storage_bucket_path`, while the new AI contract does not expose a physical object key. For AI-managed RAG uploads the backend therefore stores an explicit opaque reference:

```text
ai-rag://documents/<document_id>
```

This is not a MinIO path and must not be interpreted as one. It simply records that storage is owned by the RAG AI document service. Existing historical rows with physical storage paths remain unchanged.

## Failure handling

The backend maps these cases before returning to the frontend:

- missing/empty/unsupported file -> invalid upload;
- file larger than configured maximum -> payload too large;
- missing feature -> forbidden;
- extraction/storage quota exhausted -> payment/limit error;
- AI timeout/non-2xx/malformed response -> external service error;
- RAG query 500/502/503 -> upstream LLM failure.

## Frontend change still required

The Knowledge Base frontend currently uploads to the old extraction route. It should be changed from:

```text
POST /features/extraction/upload
```

to:

```text
POST /features/rag/documents
```

The multipart field remains `file`.
