# CEOPRO-AI — Document Storage Business Specification

W

## 1. Business purpose and scenarios

Document Storage is the maximum amount of retained document data that a subscribing business can have in CEOPRO at one time. It supports the business's continued access to reference documents and, under an explicitly defined retention policy, previously uploaded business files. The owner must understand **used, remaining, and maximum capacity**, which files occupy storage, and how to free space without unintentionally destroying historical business records.

**Scenario A — Knowledge Base:** A retailer uploads supplier manuals, policies and invoices for reference. The retained RAG source bytes occupy document storage; the AI assistant can use those documents for grounded answers. A later deletion, if implemented, should remove the document's associated chunks and correctly release counted capacity.

**Scenario B — Data Connections:** An owner uploads sales files. The current Node endpoint sends the file to hosted extraction, then stores metadata/staging/transactions, but does **not** persist the original file contents in the RAG document table. The system currently checks document-storage capacity **even though its storage-usage resolver does not count this upload**. A retention decision must precede any unified charging change.

**Scenario C — Plan changes:** A tenant reduces its plan below its current occupied capacity. Existing data must not be silently destroyed. A defined policy should restrict further uploads until within limit while preserving permitted read access and offering clear remediation.

## 2. Feature and subscription model

- Feature code: `document_storage_mb`.
- Catalog: numeric `limit`, unit `mb` (Arabic: `ميجابايت`), aggregation `max`, reset cycle `lifetime`.
- **Starter ($55/month): 1,024 MB** (1 GiB).
- **Growth ($140/month): 10,240 MB** (10 GiB).
- **Enterprise ($350/month): 51,200 MB** (50 GiB).
- Custom plans may specify a separate limit; consult accepted and active entitlement configuration.
- The backend uses binary units: one recorded MB represents **1,048,576 bytes**. UI labels are “MB/GB”; for precision these are technically MiB/GiB. Align labels with policy or explicitly document binary conversions.

**Keep limits distinct:** `document_extraction` is charged in KB of processed uploads per billing period; `document_storage_mb` measures retained data at a point in time; `rag_assistant` measures token use. Billing periods do **not** reset storage occupancy.

## 3. Current authoritative calculations

From `src/modules/features/service/capacity.service.ts`:

```text
stored_rag_bytes = SUM(rag_documents_metadata.file_size_bytes
                       WHERE tenant_id = current_tenant)
used_storage_mb = stored_rag_bytes / (1024 * 1024)
remaining_mb = max(0, effective_plan_limit_mb - used_storage_mb)
can_upload = used_storage_mb + incoming_file_bytes/(1024*1024)
             <= effective_plan_limit_mb
```

The `getCurrentCapacityUsage()` resolver does **not** sum `data_sources.collector_config.file_size_bytes`, actual MinIO object bytes, embeddings, `rag_document_chunks` content, or other application objects. The feature usage dashboard invokes this resolver for `max`-aggregation entitlements. There is no evidence in the inspected Node code of a single complete tenant storage inventory covering all storage backends.

**Example:** Starter limit 1,024 MB; recorded RAG source sizes sum to 300 MiB; reported usage is 300 MB and 724 MB remain. This result is correct for the current RAG-only formula, but may understate wider document retention if files are retained elsewhere.

**Edge-case rules:** Empty file should be rejected by upload validation. Use actual byte counts, preserve fractional MB in backend calculations, round only for display, and use precise comparison at the capacity boundary. Do not subtract physical PostgreSQL row/chunk/embedding overhead from a customer-facing source-file allowance unless the commercial definition explicitly includes it.

## 4. Data model and ownership

| Data / store                                        | Fields or contents                                                                                                           | Current owner / implication                                                                                                                 |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `rag_documents_metadata`                            | `tenant_id`, `document_id`, `file_name`, `file_size_bytes`, `source_file_content`, `storage_bucket_path`, `processed_status` | **Node RAG** writes rows and original upload bytes to PostgreSQL `BYTEA`; counted by storage quota.                                         |
| `rag_document_chunks`                               | Extracted passages and embeddings linked to document                                                                         | **Node/AI RAG** use chunks; **not** included in current storage quota. Child rows cascade when metadata is removed at DB level.             |
| `data_sources`                                      | File-import provenance within `collector_config` including `file_size_bytes`, or external connector metadata                 | **Node Data Connections** records uploaded business-file metadata, but does not preserve original bytes on this path. Not counted by quota. |
| `ingestion_jobs`, `import_staging_rows`             | Extraction/import state and structured row data                                                                              | **Node ingestion system**; not counted by document storage.                                                                                 |
| `subscription_usage`                                | Consumption record for sum-based features                                                                                    | **Features/billing**; not the authoritative source for `document_storage_mb` because this feature uses max capacity resolver.               |
| MinIO `ceopro-rag-knowledge`                        | AI-codebase RAG knowledge objects                                                                                            | **AI-team architecture**; code assumes object storage; not accounted for by Node storage resolver.                                          |
| MinIO `ceopro-extraction-results`                   | AI extraction-provenance JSON                                                                                                | **AI-team FastAPI pipeline** may write these outputs; not counted by Node resolver.                                                         |
| MinIO `ceopro-raw-ingestion`, `ceopro-ai-artifacts` | Documented raw ingestion and model artifacts                                                                                 | Defined in AI architecture; actual usage/retention and billing linkage must be verified.                                                    |

**Critical distinction:** The AI-team architecture document says raw blobs are in MinIO and PostgreSQL contains metadata, but the reviewed **Node RAG implementation explicitly stores source bytes in PostgreSQL** (`source_file_content BYTEA`) and writes a `ceopro-db://rag-documents/{id}` key. The two architectures must not be represented as one verified, unified storage implementation. Hosted Gradio also differs from the AI-team Python FastAPI pathway.

## 5. Actual upload paths

### A. Knowledge Base / RAG

1. Frontend `knowledgeBaseApi.uploadDocument()` posts to `/features/rag/documents`.
2. `src/modules/rag/route/rag.route.ts` authenticates tenant and requires `document_extraction`; Multer caps files at **2 MiB**.
3. `src/modules/rag/service/rag.service.ts` checks extraction quota **and** `document_storage_mb` capacity using incoming bytes.
4. `src/modules/rag/repo/rag.repo.ts` inserts metadata, `file_size_bytes`, and `source_file_content` in PostgreSQL.
5. After successful persistence, extraction usage is incremented separately.
6. Read/query services can submit retained document content to hosted RAG inference and persist chunks from returned sources.

Allowed RAG extensions: `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`. The service currently marks an upload `Processed` at persistence time; this is **not evidence** that AI indexing succeeded for that document. The RAG route set has list, upload, query and chunk-read endpoints; **no supported delete endpoint was found**.

### B. Business-data extraction

1. Frontend Data Connections calls `POST /data-connection`.
2. Node validates file, extraction quota and storage capacity (default file-size cap around 10 MiB, configurable).
3. File bytes are sent to hosted Gradio extraction; backend receives structured rows.
4. Node creates `data_sources` (inactive document source), `ingestion_jobs` and `import_staging_rows`.
5. Import worker promotes products and transactions.
6. Original bytes are not persisted into `rag_documents_metadata` or a verified object key on this Node path; the source stores **file-size metadata** in `collector_config`.

**Current inconsistency:** A business upload can be denied on storage capacity even though the successful upload is not subsequently counted in that same capacity total. Adding file-size metadata to the quota without proving the source file is retained would create the opposite problem: billing for files CEOPRO no longer stores. Decide and implement the retention contract first.

### C. AI-team Python pathways

The supplied AI repository has `src/ai/extraction/minio_persistence.py`, which writes extraction-result JSON into MinIO, and `src/ai/rag/data_access.py`, which reads RAG originals from MinIO. This is not proof that the active Node-hosted Gradio integration stores or charges those objects. Verify deployment, bucket ownership, lifecycle and cross-service contracts before combining usage.

## 6. Frontend and customer experience

- Billing `UsageLimitGrid.jsx` can show used, total and remaining document-storage capacity and convert MB to GB at 1,024 MB/GB.
- Frontend knowledge-base document list maps `file_size_bytes` to sizes; frontend error mapping supports detailed storage-capacity messages and the server distinguishes `STORAGE_EXCEEDED` from extraction-quota exhaustion.
- Knowledge-base API declares `documentActions: false` and lacks remove/replace actions. User cannot free quota through a verified supported UI workflow.
- Frontend RAG upload client checks a **10 MiB** per-file limit while backend RAG enforces **2 MiB**; the client and server must agree.
- On listing error, the frontend may return an unavailable/empty result without a hard failure; verify that a network error is not represented as “no documents.”

**Recommended UX:** Show one capacity meter with actual retained bytes, reliable provenance by document type, separate extraction allowance, and actionable “storage full” errors. Only offer deletion/cleanup when implemented and authorized.

## 7. Entitlements, pricing and billing

- For RAG uploads, route-level entitlement `document_extraction` is mandatory; the service also verifies `document_storage_mb` capacity.
- For business-file uploads, the service checks storage capacity as well as extraction allowance; route-level gates may differ.
- `document_storage_mb` is a MAX/lifetime capacity and does not accumulate monthly consumed MB in `subscription_usage`.
- Custom-plan infrastructure pricing includes storage limits as an estimated **GB-month** cost driver in the custom-plan pricing tests. This is **provider cost modeling**, not an actual tenant storage billing meter and does not supersede the customer entitlement.
- Upgrades, downgrades and custom plans must be validated against the current active subscription; do not silently purge content or assume an expired subscription can keep uploading.

## 8. Production gaps, ranked

| Priority | Gap                                                                                                | Why it matters                                                            |
| -------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **P0**   | Define a single explicit billable-retained-storage policy (RAG, business originals, MinIO objects) | Otherwise displayed usage does not represent the service being sold.      |
| **P0**   | Resolve business-file capacity check against RAG-only usage                                        | Uploads are blocked for capacity yet do not increase that capacity usage. |
| **P0**   | Make check-and-persist storage reservation atomic and safe under concurrency                       | Two simultaneous uploads may both pass the last available capacity.       |
| **P1**   | Choose and reconcile RAG source-of-truth storage (PostgreSQL BYTEA vs MinIO)                       | AI-team paths and Node paths use different byte-storage conventions.      |
| **P1**   | Implement authorized delete/replacement/retention lifecycle and capacity release                   | Customers otherwise cannot reclaim filled capacity.                       |
| **P1**   | Align frontend RAG 10 MiB and backend 2 MiB limits                                                 | Users can select files the server rejects.                                |
| **P1**   | Handle partial upload persistence vs extraction-usage increment, retries and cleanup               | Avoid orphaned documents, inconsistent billing and broken state.          |
| **P1**   | Define downgrade/exceeded-capacity policy and preserve read access                                 | Avoid unexpected customer data loss.                                      |
| **P2**   | Distinguish Processed status from actual AI indexing                                               | Prevent misleading knowledge-base readiness indicators.                   |
| **P2**   | Improve accurate bytes/MiB/GB UI, empty/error states and bilingual messaging                       | Better capacity predictability and support.                               |

**No new schema is automatically necessary.** First establish a single authoritative inventory of retained objects. Introduce storage-ledger/reservation metadata only if implementation requires it for cross-backend accounting, atomic writes and safe reconciliation. Any such change should be justified and migrated safely.

## 9. Proposed ownership contract

1. **Billing/Features backend** owns active entitlements, capacity policy, atomic reservations, usage calculations, and customer-facing remaining balance.
2. **Node RAG backend** owns RAG upload validation, source retention, access control, document lifecycle and mapping of RAG documents to counted bytes.
3. **Node Data Connections backend** owns whether uploaded business-file originals are retained, their storage keys, and associated lifecycle; ingestion jobs and historical business facts are separate from file retention.
4. **AI team** owns approved AI-managed object-storage writers and AI chunking/indexing pipelines; must report retained object size/ownership/deletion according to an agreed contract, not silently bypass capacity.
5. **Frontend** shows backend-authoritative figures and does not claim successful indexing, retention or deletion until confirmed.

Cross-tenant storage keys must be isolated; credentials must never be exposed in responses. Access to an uploaded file must not be inferred merely from knowing its document ID or object key.

## 10. Independent calculation and example tests

**Simple capacity checks:**

```text
used_bytes = SUM(eligible_retained_source_file_bytes_for_tenant)
used_mib = used_bytes / 1_048_576
limit_bytes = entitlement_limit_mb * 1_048_576
can_upload = used_bytes + incoming_retained_bytes <= limit_bytes
remaining_bytes = max(0, limit_bytes - used_bytes)
```

This is a **recommended future cross-store contract**; the current implemented authoritative resolver only sums RAG metadata rows. Do not begin charging new object categories without proving they are retained and covered by plan policy.

**Boundary fixtures:** 1,023, 1,024, 1,048,575, 1,048,576 and 1,048,577 bytes; zero-byte rejection; exactly at limit; one byte above. Check raw bytes for comparisons, display rounding only after enforcement. Ensure no cross-tenant rows or objects appear in the sum.

**Concurrency fixture:** With one MiB remaining, launch two simultaneous 0.75-MiB RAG uploads. The final counted byte balance must not exceed the plan limit and rejected uploads must not leak persisted data or leave incorrect charges.

**Retention fixture:** Create a RAG original and associated chunks, then exercise an authorized deletion **when that endpoint exists**; verify all document-related records and physical bytes are released by the confirmed policy and historical business facts unrelated to the source remain intact.

## 11. E2E acceptance checklist

All unchecked until actual testing evidence is recorded:

- [ ] Verify Starter 1,024 MB, Growth 10,240 MB and Enterprise 51,200 MB against active plan data.
- [ ] Verify max/lifetime entitlement and custom-plan limits without billing-period usage resets.
- [ ] Independently calculate RAG source bytes and compare DB, API and billing UI.
- [ ] Verify exact-limit and one-byte-over-limit uploads using integer-byte arithmetic.
- [ ] Test simultaneous RAG uploads near capacity and prevent over-allocation.
- [ ] Verify RAG upload saves actual file bytes and correct `file_size_bytes`.
- [ ] Validate 2 MiB backend RAG cap and correct frontend matching restrictions.
- [ ] Verify extraction and storage quotas remain independent with correct failure messages.
- [ ] Verify business uploads are accounted for according to proven raw-file retention policy, not metadata alone.
- [ ] Verify source-ownership consistency between Node PostgreSQL RAG and AI MinIO paths.
- [ ] Verify retries, failed persists and usage-charge errors do not create inconsistent quotas.
- [ ] Verify authorized delete/replace/retention behavior and storage reclamation (currently BLOCKED if unsupported).
- [ ] Verify no tenant can view/delete another tenant's source or infer stored raw bytes.
- [ ] Verify downgrade and full-capacity behavior without silent data deletion.
- [ ] Verify raw object and chunk storage accounting is not double-counted under chosen policy.
- [ ] Verify RAG indexing status corresponds to actual processing, not merely upload acceptance.
- [ ] Verify billing usage formatting, bilingual labels and RTL rendering.
- [ ] Verify test diagnostics distinguish missing implementation, policy ambiguity, AI outage and genuine calculation defects.
- [ ] Keep live AI/MinIO tests opt-in; run deterministic API/DB/Playwright tests against isolated test infrastructure.
- [ ] Verify report output includes PASS/FAIL/BLOCKED with table/endpoint, expected bytes and observed bytes evidence.

## 12. Implementation and release sequence

1. Approve business rule: what exact original/document objects count and how storage is retained/released.
2. Make a definitive Node + AI object-storage ownership and usage map, with actual deployment confirmation.
3. Reconcile data-connection business-file storage checks with retention and authoritative usage; avoid charging transient files.
4. Implement atomic quota reservation/persist/release semantics and error recovery where applicable.
5. Add deletion/replacement and retention enforcement only with explicit access control, audit and history policy.
6. Align RAG client/server upload constraints; separate “uploaded” from “indexed.”
7. Extend existing Playwright/API/database suites with independent byte-based assertions and opt-in live object-store verification.
8. Validate usage dashboard, plan changes, Arabic/English and RLS in a dedicated test database.

**Release criterion:** Every tenant-visible storage figure must match the approved inventory of actual retained documents; concurrent uploads cannot exceed the entitlement; deletions release capacity according to documented policy; no tenant can access another tenant's files. The existing RAG source accounting is a useful foundation, not a complete cross-system storage service.

---

## Verified implementation references

**Node backend:** `src/config/production-plans.ts`; `src/modules/features/catalog.ts`; `src/modules/features/service/capacity.service.ts`; `src/modules/features/service/usage.service.ts`; `src/modules/features/repo/usage.repo.ts`; `src/modules/rag/route/rag.route.ts`; `src/modules/rag/service/rag.service.ts`; `src/modules/rag/repo/rag.repo.ts`; `src/modules/rag/types/rag.types.ts`; `src/modules/dataconnection/service/dataconnection.service.ts`; `src/modules/dataconnection/repo/dataconnection.repo.ts`; `prisma/schema.prisma`; `prisma/migrations/20261005110000_add_rag_source_file_content/migration.sql`.

**Frontend:** `src/features/knowledge-base/api/knowledgeBaseApi.js`; `src/features/knowledge-base/utils/ragErrorFeedback.js`; `src/features/billing/components/UsageLimitGrid.jsx`; related knowledge-base pages and localization dictionaries.

**AI team:** `src/infrastructure/MINIO_STORAGE_ARCHITECTURE.md`; `src/ai/extraction/minio_persistence.py`; `src/ai/extraction/ingestion_pipeline.py`; `src/ai/rag/data_access.py`; `src/ai/main.py`.

These references reflect the **saved snapshots reviewed**, not proof of deployed service health or any live quota usage.
