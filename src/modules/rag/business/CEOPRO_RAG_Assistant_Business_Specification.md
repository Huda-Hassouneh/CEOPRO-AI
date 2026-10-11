# CEOPRO-AI — Feature 12: RAG Assistant (`rag_assistant`)

## 1. Executive summary and business purpose

The RAG Assistant helps a tenant ask questions grounded in **their own knowledge documents** with inspectable supporting evidence, rather than treating an LLM's general knowledge as company policy. Example: a medical laboratory manager uploads internal preparation guidelines and asks, “What fasting instructions does our approved policy give reception staff?” CEOPRO should answer only when the relevant uploaded material supports the response, expose the cited passage, and say when the material does not establish an answer.

**Value:** faster internal document lookup, consistent operational answers, reduced manual searching, and auditable source attribution. **Not a substitute for:** an authoritative transactional database query, professional judgment, or a guarantee that every model answer is correct.

A satisfactory flow: (1) upload a valid document; (2) confirm it is genuinely available for retrieval; (3) submit a question; (4) retrieve relevant evidence from only the authorized tenant; (5) generate an appropriately grounded answer; (6) let the user open a real citation; (7) meter actual AI tokens, with correct subscription enforcement.

## 2. Subscription and related feature boundaries

| Standard plan | Monthly USD price | `rag_assistant` token allowance / billing period |
| ------------- | ----------------: | -----------------------------------------------: |
| Starter       |               $55 |                                          100,000 |
| Growth        |              $140 |                                          500,000 |
| Enterprise    |              $350 |                                        2,000,000 |

`rag_assistant` is a **limit / SUM / billing_period** catalog feature, unit **tokens**. Custom plans may override the number. `document_extraction` is a separate **KB processed / billing period** allowance; `document_storage_mb` is a **retained storage** capacity limit. Upload/list routes currently require `document_extraction`, upload checks remaining extraction + storage capacity, while querying requires `rag_assistant`. The front-end RAG route and composer are additionally gated by `rag_assistant`.

Token accounting currently prefers `token_usage.total_tokens` (aliases `totalTokens` or `total`); otherwise it sums input/prompt and output/completion token fields, floors the nonnegative total and increments `subscriptionUsage.current_usage`. This is **actual reported usage after the AI call**, not a reliable pre-call token reservation. If the upstream gives no usable token numbers, the backend records **0** tokens for that answer. Check the exact reset window and plan transition behavior in the subscription engine when testing.

**Quota example:** With a 100,000-token allowance, 12,000 tokens used and a subsequent model response reporting 1,200 total tokens, remaining usage becomes `100000 - 12000 - 1200 = 86800` tokens. This only describes correct accounting if that response is charged exactly once.

## 3. Current frontend experience — reviewed code

Real React RAG page: `frontend/src/features/knowledge-base/pages/RagAssistantPage.jsx` with `RagChatWindow`, `KnowledgeBasePanel`, `SourceCitationList`, `EvidencePanel`, `useRagChat`, `useKnowledgeDocuments`, and `knowledgeBaseApi`.

- Working API-client paths exist for document list/upload, chat and citation-chunk detail.
- Knowledge Base document search/type/sort are currently **client-side over the returned page** (server list defaults to 3 per page); users may not be searching the complete library.
- Frontend displays an upload limit of **10 MiB**, whereas backend enforces **2 MiB**.
- Frontend maps every document status to `active`, rather than using `processed_status` (`Pending`, `Processed`, `Failed`).
- `listSessions()` returns `{ sessions: [], available: false }`; chat messages are held in React state, so persistent conversation sessions are **not implemented**. The frontend chat call does **not** submit the backend's supported `history_json`.
- Frontend sends one question through `POST /features/rag/query?query_text=...&top_k=5`; attachments are explicitly unsupported.
- **Citation mapping defect:** API maps `source.chunk_id` into a frontend property named `documentId`, displays generic `Source Document {index}`, and drops real `document_id`, `document` filename and supporting text. The UI happens to use that mislabeled ID as the chunk lookup key, but accurate source identity, descriptive citation names, and evidence excerpts are lost. Verify `GET /features/rag/chunks/:chunk_id` links and the mapping after any fix.
- Document actions/preview/streaming/session persistence are marked unavailable in the client capabilities; do not claim they work.

## 4. Active Node backend routes and flow

Mount: `app.use('/features/rag', ragRouter)` in `src/app.ts`.

| Endpoint                             | Current purpose               | Entitlement/authorization                                                          |
| ------------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------- |
| `GET /features/rag/documents?page=N` | Tenant documents, pagination  | User+tenant + `document_extraction`                                                |
| `POST /features/rag/documents`       | Store original source file    | User+tenant + `document_extraction`, also checks extraction and storage capacities |
| `POST /features/rag/query`           | Query hosted AI for an answer | User+tenant + `rag_assistant`                                                      |
| `GET /features/rag/chunks/:chunk_id` | Inspect a cited chunk         | User+tenant + `rag_assistant`                                                      |

Source: `src/modules/rag/{route,controller,service,repo,client,types}`.

**Upload:** Multer memory storage, one file, max **2 × 1,024 × 1,024 bytes**, extensions `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`. `uploadRagDocument` validates extension/size, checks document extraction (ceil bytes/1,024 KB) and storage capacity, stores original bytes in `rag_documents_metadata.source_file_content` (Postgres BYTEA), sets `storage_bucket_path` to a `ceopro-db://` URI, immediately sets `processed_status='Processed'`, then increments `document_extraction` usage. **It does not call the AI service or create embeddings at upload time.** This is a misleading processing status unless the product explicitly defines “Processed” as “original bytes safely retained,” not “ready/indexed.”

**Query:** load at most **10 most recently uploaded tenant documents** marked `Processed`. For `.txt` and `.md`, send text; for other supported types, send Base64 of original bytes; if originals are absent but DB chunks exist, send concatenated chunk text. Each AI-facing filename includes the document UUID to disambiguate same-named files. Call hosted Gradio `rag_answer` with positional `[documents, question, top_k, history]`, timeout **120 seconds**. Map returned citations to local documents; insert cited passage text into `rag_document_chunks` on demand, using an advisory transaction lock to prevent duplicate citation chunks for the same document/text. Increment RAG usage from provider-reported tokens, then return answer and sources.

**Operational consequence:** query-time source bytes can be resent and reparsed for every request, even if the original was already uploaded. Old documents outside the latest 10 may be omitted silently. Upstream citations are not in themselves proof of correctness; validate cited passages against actual document content.

## 5. AI team implementation — separate pathway

The supplied Python AI repository contains a **database-backed** RAG pipeline:

- `src/ai/rag/data_access.py`: tenant-document metadata, MinIO reads, chunk persistence and vector fields.
- `src/ai/rag/chunking.py`, `embeddings.py`: chunking and dense embeddings.
- `src/ai/rag/bm25_index.py`, `faiss_index.py`, `hybrid_retrieval.py`, `reranking.py`, `pipeline.py`: lexical + vector retrieval, fusion, reranking and context construction.
- `src/ai/rag/llm_client.py`: grounded answer generation, optional conversation history, token usage; Groq by default with configurable local or paid compatible provider.
- `src/ai/main.py`: authenticated `POST /rag/query`; reads persisted tenant vectors/chunks and returns answer/sources/token usage.
- AI ingestion `ingest_pending_documents()` reads `Pending` documents from MinIO, extracts/chunks/embeds, persists `rag_document_chunks`, and marks status `Processed` or `Failed`.

**Critical integration distinction:** CEOPRO Node currently calls a **hosted Gradio `rag_answer` API** and retains original files in PostgreSQL. It does **not** call Python's `POST /rag/query`, provision the MinIO ingestion contract, or invoke the Python indexing worker on RAG upload in the reviewed snapshot. Thus the AI team's robust hybrid retrieval pipeline **exists in source** but must **not** be described as the current end-to-end web runtime. The hosted Gradio Space's own implementation is not contained in the supplied AI ZIP; the exact retrieval model, generation provider and indexing internals for that service remain unverified.

## 6. Database sources and ownership

| Table / data                                          | What it holds                                                               | Primary owner in current web flow                                                                                   |
| ----------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `companies` / tenant memberships                      | Tenant and authorized users                                                 | Node auth/tenant layers                                                                                             |
| `rag_documents_metadata`                              | Original document metadata, `source_file_content`, `processed_status`, size | Node RAG upload; AI has a separate metadata ingestion path                                                          |
| `rag_document_chunks`                                 | Cited text, optional 384-dim `embedding`, `embedding_model_version`         | Node creates citation chunks at query time; AI Python can create embedded retrieval chunks in its separate workflow |
| `subscriptions`, `plans`, `plan_features`, `features` | Effective customer entitlements                                             | Node subscription/billing/features                                                                                  |
| `subscriptionUsage` / `subscription_usage`            | Metered token and extraction usage                                          | Node entitlement/usage layer                                                                                        |
| MinIO RAG objects                                     | AI-origin document originals, where configured                              | AI team's storage workflow; not the same as Node's `ceopro-db://` URI                                               |

Database schema establishes `(tenant_id, document_id)` constraints for metadata/chunks; RLS is enabled on both tables. Node repo calls `setTenantContext` within Prisma transactions before tenant-scoped database queries and returns source-chunk content only when the tenant-scoped lookup finds it.

**Important:** Product sales in `transactions`, invoice data and other operational tables are **not automatically all searchable** through the active Node-hosted Gradio path. A separate structured-data retrieval layer may exist inside AI Python, but it is not proof that the current web client uses it. Adding an arbitrary sales CSV to Data Connections does not automatically make it a RAG knowledge document.

## 7. Calculations and quality controls

### Subscription usage

`total_tokens = max(0, floor(provider_total_tokens))` when a valid explicit total is returned. Otherwise `floor(prompt_or_input_tokens + completion_or_output_tokens)` if valid, positive. Increment `rag_assistant` usage after the successful call. The billing-period allowance is `plan_limit - cumulative_charged_tokens`, floored at zero for UI display.

**Risks:** absent provider usage may become a free/unmetered answer; concurrent calls can each see remaining quota and overspend the limit; a call near its limit can exceed capacity after generation; a partial failure between answer generation, citation persistence and usage charging can produce inconsistent states; retries can charge twice unless idempotency is defined. Determine whether the quota policy should reserve a maximum/estimated budget and reconcile on actual completion; do not silently invent charges for missing provider usage.

### Retrieval quality

The current Node-hosted Gradio contract accepts `top_k` in 1–20. Relevance scores are upstream outputs; their scale and meaning must be verified with the actual hosted service. The Python team implementation uses hybrid BM25+dense vector retrieval and reranking, but these are not automatically the active Node calculation. QA should measure precision at k, source relevance, citation correctness and calibrated abstention on a controlled question-answer corpus.

### Storage vs extraction

Uploaded RAG file contributes `ceil(file_bytes / 1,024)` to document extraction usage and `file_bytes / (1,024^2)` MiB of retained original storage if counted. Upload accepts `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`. Extraction quota is metered over a billing period; retained storage is simultaneous capacity.

## 8. Known release gaps and priority

| Priority | Gap / corrective work                                                                                                                                                                                                       |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P0**   | Ensure document `Processed` status means actually retrievable/ready; implement truthful pending/processing/failed transitions or explicitly distinguish stored-from-indexed for the hosted model.                           |
| **P0**   | Fix frontend citation mapping: preserve real `document_id`, `chunk_id`, filename, excerpt and score; fetch the correct chunk and show original evidence, not generic labels.                                                |
| **P0**   | Enforce token budgets safely under concurrency, large calls and retries; decide missing-usage policy and verify billing-period resets.                                                                                      |
| **P0**   | Verify real hosted Gradio `rag_answer` input/output, actual citation behavior, provider token usage, errors and answer grounding.                                                                                           |
| **P1**   | Decide authoritative RAG architecture: current query-time Gradio reconstruction versus AI-team MinIO/pgvector indexed pipeline; align upload, processing, query and deletion contracts instead of mixing half of each path. |
| **P1**   | Fix frontend 10 MiB vs backend 2 MiB upload-limit mismatch and validate file signature/content/empty usable text, not extension alone.                                                                                      |
| **P1**   | Make RAG upload/storage/extraction usage transactionally consistent; prevent quota bypass and partial charges under simultaneous uploads/failures.                                                                          |
| **P1**   | Address current latest-10-document ceiling and provide explicit document-selection/search scope, or a supported indexed whole-library retrieval strategy.                                                                   |
| **P1**   | Align `document_extraction` upload/list access and `rag_assistant` UI access with intended product authorization; test direct backend API bypass attempts and role policies.                                                |
| **P1**   | Maintain cross-tenant isolation across original files, chunks, citations, any AI/vector indexes, and source lookups.                                                                                                        |
| **P2**   | Correct document status display; implement meaningful error/empty states, source previews and deletion according to storage policy.                                                                                         |
| **P2**   | Implement conversation-history submission or explicitly mark chat as single-turn; do not advertise persisted sessions while `listSessions()` is stubbed.                                                                    |
| **P2**   | Extend document filtering beyond only the three records on the current UI page, and verify bilingual/RTL presentation.                                                                                                      |

## 9. Recommended implementation ownership

**Node backend team:** subscription entitlements, secure tenant context, upload lifecycle, quota charging/reservations, document database ownership, hosted AI transport, response validation, citation-ID mapping, chunk permission checks and API errors.

**AI team:** reliable document parsing, indexing/retrieval, reranking, generation, token metadata, source relevance, evidence contract and inference failure semantics. Determine whether the web product should use Gradio or FastAPI/MinIO as its authoritative RAG service; avoid parallel conflicting definitions of ready status.

**Frontend team:** upload limits/formats, knowledge library, truthful processing statuses, chat UX/history, citation clicks/evidence, quota display, error handling and Arabic/English localization.

**Shared contract to agree:** upload accepted vs ready, supported formats, document visibility, citation fields/IDs, source score scale, token-usage schema, error codes, retries, deletion/reindexing, cost attribution and data-retention guarantees.

## 10. End-to-end test plan (reuse existing CEOPRO framework)

Three test modes:

1. **Deterministic real-system E2E:** Playwright + actual Node API + separate PostgreSQL test DB, controlled documents, tenant/subscription fixtures, authorized chunk records; no mocked backend response. Verify persistence, list, document quotas, citation access, UI and security.
2. **AI contract/integration:** test request serialization, sources/usage parsing, zero/malformed token usage, citation mapping, upstream errors and retries against controlled upstream responses. Label simulations as **contract**, not live E2E.
3. **Live AI E2E (opt-in):** use a safe test tenant and real hosted Gradio endpoint, upload known documents, query for grounded facts, verify exact cited passages, source opening, token usage, and isolation. Test separate Python FastAPI/MinIO RAG path on its own only when intentionally configured. Never equate it with the hosted Gradio runtime.

### Acceptance checklist

- [ ] Standard-plan allowances (100k/500k/2m tokens), custom plans and billing-period resets verified.
- [ ] Upload types `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx` validated; corrupt/empty/wrong-signature files safely rejected.
- [ ] Exact backend 2 MiB boundary and frontend display aligned.
- [ ] RAG upload actually stores bytes with accurate tenant, filename, size and status.
- [ ] Processing state matches actual readiness and failure conditions.
- [ ] Extraction/storage quotas charged consistently and safely under concurrency and retries.
- [ ] Zero documents and not-ready documents do not generate fabricated answers.
- [ ] Up to 10-document current selection behavior verified; >10-document omission made explicit or remedied.
- [ ] Hosted Gradio `rag_answer` contract tested with `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx` where supported.
- [ ] AI failures, 120-second timeout, null/malformed responses and retries produce correct diagnostic errors.
- [ ] Token totals from provider independently checked; missing usage is flagged, not silently accepted as accurate zero.
- [ ] Concurrent and near-limit chat calls cannot exceed allowed usage without policy-defined handling.
- [ ] Duplicate requests and partial failures do not incorrectly double-charge or lose chargeable usage.
- [ ] Answers on controlled corpus cite the correct source document and relevant passage.
- [ ] Citation `document_id` and `chunk_id` preserved; real chunk-detail endpoint returns matching text.
- [ ] Unsupported/no-evidence questions abstain appropriately; hallucination/prompt-injection cases tested.
- [ ] Same-named documents map to the correct UUID and citation.
- [ ] Cross-tenant document/chunk/retrieval access denied through both UI and direct API.
- [ ] RAG uploads, Data Connections uploads and other business data remain properly separated.
- [ ] Frontend sessions/history handling matches supported API capabilities; bilingual/RTL UX verified.
- [ ] AI Python MinIO/pgvector ingestion has separate opt-in integration coverage, not misreported as Node's active Gradio flow.
- [ ] Browser/network/SQL diagnostics, screenshots and HTML/JSON reports are produced using existing test infrastructure.

## 11. Representative business cases

**Case A — grounded answer.** Upload an approved procedure containing a specific operating instruction. Ask a direct question. Expected: answer accurately reflects the document and links to a verifiable evidence passage.

**Case B — insufficient evidence.** Ask a question whose answer is not present. Expected: an explicit limitation; no fabricated source or unsupported certainty.

**Case C — tenant isolation.** Tenant A uploads a confidential supplier agreement. Tenant B asks about it. Expected: no retrieval or leakage, including via chunk-detail ID enumeration.

**Case D — quota exhaustion.** A tenant has only a small token balance. Concurrent questions should obey the chosen reservation/reconciliation rules; the usage card and database must agree.

**Case E — same filename.** Upload two different `policy.pdf` files. Returned citations must open the correct tenant-owned document and passage, not an arbitrary matching name.

**Case F — incomplete processing.** A stored document has no indexed/searchable content. The UI should not falsely advertise it as ready under the chosen architecture.

## 12. Definition of done and next actions

1. Decide and document the authoritative AI retrieval path (Node + Gradio vs Python indexed RAG) without disrupting current customers.
2. Fix source ID/filename/excerpt rendering and make the evidence panel verify the real chunk.
3. Correct upload/processing statuses and source selection limits.
4. Align upload-size validation and entitlement gates; make usage charging robust for RAG tokens and document bytes.
5. Run deterministic tests and opt-in live hosted-AI tests, produce per-stage diagnostic evidence, and only then mark the feature production-ready.

**Status:** Core Node/React user flow and AI-team pipeline components exist, but the integration, correctness and security properties above **remain to be verified or fixed**. Do not mark this feature completed based solely on the presence of an endpoint, an upload confirmation or a plausible AI answer.
