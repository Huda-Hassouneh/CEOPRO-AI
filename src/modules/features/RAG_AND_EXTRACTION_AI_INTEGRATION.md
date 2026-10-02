# RAG and Extraction AI Integration

## Ownership
The CEOPRO backend owns authentication, tenant isolation, entitlement/capacity enforcement, upload validation, usage accounting, metadata persistence, and the frontend-facing response. The AI service owns extraction/RAG processing and returns contract data only.

## Configuration
- `AI_SERVICE_URL` defaults to `http://localhost:8000`.
- `AI_SERVICE_USE_MOCKS=true` enables the existing mock behavior.

## Extraction flow
1. Backend validates tenant/user, file extension/size, `document_extraction` quota, and `document_storage_mb` capacity.
2. `client/features-ai.client.ts` sends multipart `POST /extraction/upload` and forwards the Authorization header when present.
3. The AI response must include `minio_object_key` because the backend persists document metadata against that object key.
4. Backend persists metadata and increments extraction usage in KB.

Expected response fields currently consumed include `job_id`, `template_mode`, `is_template_compliant`, row counts, loss/coverage metrics, `row_outcomes`, `promotion`, `currency_resolution`, and `minio_object_key`.

## RAG flow
1. Backend validates query text/history/top-k and the `rag_assistant` entitlement.
2. Client sends `POST /rag/query` with `query_text`, `top_k`, optional `history_json`, and forwarded Authorization.
3. Backend returns `answer` and `sources` and charges actual token consumption when supplied by the AI response.
4. Chunk detail remains tenant-scoped through the existing RAG service/repository path.

## Failure contract
Transport timeouts, malformed JSON, and non-2xx upstream responses are mapped to the existing external-service errors. Server-side RAG failures (500/502/503) retain the existing LLM-specific mapping.

## Integration rule
Do not move tenant authorization, entitlement enforcement, usage accounting, or database writes into the AI service. AI transport stays in `client/`; CEOPRO business rules stay in controller/service/repo layers.
