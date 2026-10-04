# CEOPRO RAG Document Upload — Backend Implementation

## What changed

The Knowledge Base/RAG upload flow now has its own backend module and no longer relies on the Connected Data extraction upload route.

Public CEOPRO API:

```text
POST /features/rag/documents
```

Upstream AI API:

```text
POST /rag/documents
```

The backend forwards the incoming Bearer JWT and sends multipart field `file`.

Supported document formats:

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

## Backend architecture

```text
src/modules/rag/
├── route/rag.route.ts
├── controller/rag.controller.ts
├── service/rag.service.ts
├── repo/rag.repo.ts
├── client/rag.client.ts
├── types/rag.types.ts
├── README.md
└── RAG_AI_INTEGRATION.md
```

Flow:

```text
Route
→ Controller
→ Service
→ Repo / Prisma
→ Client
→ CEOPRO AI service
```

RAG query, document list, chunk lookup and document upload now live under this dedicated module while keeping the existing `/features/rag/*` public API paths.

## Mock mode

Mock mode is intentionally ON by default:

```env
RAG_AI_USE_MOCKS=true
```

If the variable is absent, the code still behaves as `true`.

This allows frontend/backend development before the AI service is available.

## Connect to the real AI service

Use:

```env
AI_SERVICE_URL=http://localhost:8000
RAG_AI_USE_MOCKS=false
```

Then restart the Node backend.

No source-code change is required.

The RAG client will send:

```http
POST {AI_SERVICE_URL}/rag/documents
Authorization: Bearer <incoming CEOPRO JWT>
Content-Type: multipart/form-data
```

with multipart field:

```text
file
```

## CEOPRO-side enforcement

Before calling AI, the backend still checks:

- authenticated user and tenant;
- `document_extraction` entitlement/quota;
- `document_storage_mb` capacity;
- non-empty file;
- maximum configured upload size;
- allowed RAG extension.

After a successful AI response, the backend stores local RAG document metadata and increments `document_extraction` usage in KB.

Because the new AI response does not expose a physical MinIO/object-storage key while the existing schema requires `storage_bucket_path`, AI-managed uploads store this explicit opaque reference:

```text
ai-rag://documents/<document_id>
```

It is not a MinIO path. It marks the document as storage-managed by the RAG AI service.

## Frontend follow-up

The existing Knowledge Base frontend currently posts uploads to:

```text
/features/extraction/upload
```

It must be changed to:

```text
/features/rag/documents
```

The multipart field remains `file`.

## Verification

A focused contract test was added:

```bash
npm run test:rag
```

Current focused result:

```text
6 passed
0 failed
```
