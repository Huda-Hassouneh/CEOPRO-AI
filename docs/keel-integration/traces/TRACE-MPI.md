# Source trace refinement — MPI

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified MPI lineage](../evidence/phase0r/SCHEMA_LINEAGE_MPI.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ENT-001; MPI-001

## MPI-001 — BUSINESS subject and company ownership

Proposed behavior remains: Reuse Python subject scorer; enforce enum and BUSINESS subject ID contract before evidence writes.

Acceptance specification: `AT-MPI-001` — Wrong BUSINESS ID; unsupported case; other tenant. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/service/mpi.policy.ts:20:1::validateMpiSubject | backend/src/modules/mpi/repo/mpi.repo.ts:13:1::getReviewsForMpi | backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/routers/mpi.py:13::mpi_summary | backend/src/ai/mpi/data_access.py:16::load_scored_reviews`.

**Schema/access:** public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** Raw subject_type str; BUSINESS subject_id is ignored by data_access rather than explicitly checked against company; unsupported type raises ValueError.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-002 — PRODUCT subject existence ownership

Proposed behavior remains: Add explicit active product ownership lookup; no reviews is not proof subject exists.

Acceptance specification: `AT-MPI-002` — Missing product; deleted/cross-tenant product. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/repo/mpi.repo.ts:13:1::getReviewsForMpi | backend/src/modules/mpi/service/mpi.policy.ts:20:1::validateMpiSubject`.

**Schema/access:** public.companies; public.products; public.reviews; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/data_access.py:16::load_scored_reviews | backend/src/ai/mpi/pipeline.py:77::get_subject_mpi`.

**Schema/access:** public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** No explicit active-product existence/ownership lookup before load_scored_reviews; missing reviews not equivalent to valid subject.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-003 — COMPETITOR global-vs-tenant identity

Proposed behavior remains: Python uses global_competitor_id joined through tenant_competitors; map Node subject ID deliberately at API adapter.

Acceptance specification: `AT-MPI-003` — Tenant link absent; private competitor country leak. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/repo/mpi.repo.ts:13:1::getReviewsForMpi | backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/data_access.py:66::load_country_context | backend/src/ai/mpi/data_access.py:16::load_scored_reviews`.

**Schema/access:** public.companies; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-004 — Review eligibility future safety duplicates

Proposed behavior remains: Add allowed/safe/nonempty/nonfuture distinct newest-sample filter before unchanged Python scoring.

Acceptance specification: `AT-MPI-004` — Multiple sentiment rows; future reviews; unsafe source; 101 reviews. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/service/mpi.policy.ts:28:1::eligibleMpiReviews | backend/src/modules/mpi/repo/mpi.repo.ts:13:1::getReviewsForMpi`.

**Schema/access:** public.companies; public.products; public.reviews; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/data_access.py:16::load_scored_reviews | backend/src/ai/mpi/pipeline.py:40::_usable_reviews`.

**Schema/access:** public.reviews; public.sentiment_results

**Missing/unequal edge:** Query joins scored rows but does not implement Node safe/allowed/nonfuture/nonempty/dedup/newest-100 eligibility filters.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-005 — Scored review classification lifecycle

Proposed behavior remains: Reuse Python sentiment_results writer and pending/import analysis; avoid repeated classification charges when rendering summaries.

Acceptance specification: `AT-MPI-005` — Unanalyzed reviews; model unavailable; same review retries. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/client/mpi.client.ts:81:1::requestMarketIntelligence | backend/src/modules/mpi/client/mpi.client.ts:65:1::buildMarketIntelligenceData`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Node submits eligible text sample to external Gradio intelligence client; not the same persisted sentiment_results classification lifecycle as Python.

**PYTHON entry and UI boundary:** POST /sentiment/analyze-pending @ backend/src/ai/routers/sentiment.py:13 | POST /reviews/import @ backend/src/ai/routers/reviews.py:48. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/sentiment/pipeline.py:34::classify_and_store_reviews | backend/src/ai/routers/reviews.py:29::_analyze_imported_reviews`.

**Schema/access:** public.billing_trials; public.reviews; public.sentiment_results; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-006 — Low sample status vs numeric score

Proposed behavior remains: Node suppresses reliable score under minimum; Python returns OK plus nested LOW_SAMPLE_SIZE and dampened score. Approve public semantics without rewriting math.

Acceptance specification: `AT-MPI-006` — 0/1/4/5 reviews; env minimum >5; dashboard zero vs unknown. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/service/mpi.policy.ts:49:1::mpiSampleDecision | backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/cold_start.py:33::assess | backend/src/ai/mpi/pipeline.py:77::get_subject_mpi`.

**Schema/access:** public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-007 — Weighted score contribution and comparison

Proposed behavior remains: Keep Python recency/reliability/volume damping and compare_subjects meaningful comparison guard; retain contribution evidence.

Acceptance specification: `AT-MPI-007` — Sparse comparison; missing date; no comparable score. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/client/mpi.client.ts:81:1::requestMarketIntelligence | backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** Node delegates scoring via upstream model response; does not own Python weighted-score implementation to port.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/scoring.py:149::compute_mpi | backend/src/ai/mpi/pipeline.py:154::compare_subjects`.

**Schema/access:** public.reviews; public.sentiment_results

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-008 — Market perception access and sentiment use

Proposed behavior remains: Python MPI mounted under market_intelligence; map separate Node market_perception and sentiment_analysis records with no double charging cached reads.

Acceptance specification: `AT-MPI-008` — Market intelligence included perception excluded; summary replay. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16 | REGISTERED_GUARD use(requireFeatureAccess('business_recommendations')) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requireFeatureAccess("dashboard_analytics")) @ backend/src/modules/dashboard/route/dashboard.route.ts:19 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:46 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:51 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:61 | REGISTERED_GUARD post(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary | backend/src/middleware/validators/validateFeatures.ts:35:37::requireFeatureAccess`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /dashboard/products/{product_id}/forecast @ backend/src/ai/routers/dashboard.py:401 | GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/core/entitlements.py:51::requires | backend/src/ai/routers/mpi.py:13::mpi_summary`.

**Schema/access:** public.billing_trials; public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** MPI is mounted under market_intelligence; separate market_perception Boolean entitlement absent; scored summary itself has no sentiment reservation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-009 — Evidence model revision and history

Proposed behavior remains: Reuse evidence_records FACT/UNKNOWN and constraint-safe explanation; include review IDs/eligible range/model version and status in additive typed result envelope.

Acceptance specification: `AT-MPI-009` — No analyzed review; NULL model version; SQL shape regression. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/repo/mpi.repo.ts:70:1::persistMpiEvidence | backend/src/modules/mpi/service/mpi.service.ts:7:1::getMpiSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/mpi/evidence.py:13::insert_evidence_record | backend/src/ai/mpi/pipeline.py:77::get_subject_mpi`.

**Schema/access:** public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## MPI-010 — Three-scope dashboard refresh states

Proposed behavior remains: Python has no direct frontend /mpi/summary client match; add explicit scope selectors and real API states while retaining existing market sentiment views.

Acceptance specification: `AT-MPI-010` — Absent subject; LOW_SAMPLE_SIZE; retry; cross-tenant identifier. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14. UI: frontend/src/features/market-intelligence/api/mpiApi.js::mpiApi.getSummary; CustomerPerceptionPage.jsx.

**Exact source roots:** `backend/src/modules/mpi/controller/mpi.controller.ts:11:1::getSummary | frontend/src/features/market-intelligence/api/mpiApi.js:5:3::mpiApi.getSummary`.

**Schema/access:** public.companies; public.evidence_records; public.products; public.reviews; public.subscriptions; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /mpi/summary @ backend/src/ai/routers/mpi.py:13. UI: No direct frontend /mpi/summary request found; existing market-intelligence sentiment/comments are separate read models.

**Exact source roots:** `backend/src/ai/routers/mpi.py:13::mpi_summary | backend/src/ai/mpi/pipeline.py:77::get_subject_mpi`.

**Schema/access:** public.companies; public.evidence_records; public.global_competitors; public.reviews; public.sentiment_results; public.tenant_competitors

**Missing/unequal edge:** No direct three-scope /mpi/summary client/UI join found; preserve actual endpoint and add approved UI, not synthetic success.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
