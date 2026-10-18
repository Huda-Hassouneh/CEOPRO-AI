import fs from "node:fs";
import path from "node:path";
import type { FullConfig, Reporter, Suite, TestCase, TestResult } from "@playwright/test/reporter";

type Options = { outputFile?: string };
type RecordRow = Record<string, unknown>;

export default class DashboardDiagnosticsReporter implements Reporter {
  private readonly outputFile: string;
  private rows: RecordRow[] = [];
  private startedAt = Date.now();

  constructor(options: Options = {}) { this.outputFile = options.outputFile || "tests/reports/dashboard/diagnostics.json"; }
  onBegin(_config: FullConfig, _suite: Suite) { this.startedAt = Date.now(); }

  onTestEnd(test: TestCase, result: TestResult) {
    const annotationList = [...test.annotations, ...result.annotations];
    const annotations = Object.fromEntries(annotationList.map(item => [item.type, item.description || true]));
    const metricChecks = annotationList.filter(item => item.type === "metric-check").map(item => item.description);
    const uiMetrics = annotationList.filter(item => item.type === "ui-metric").map(item => item.description);
    const skipped = result.status === "skipped";
    const failureCategory = annotations["failure-category"] || (result.error ? this.classify(result.error.message || "") : null);
    this.rows.push({
      test: test.title,
      mode: annotations.mode || (test.location.file.includes("data-integration") ? "data-integration-e2e" : test.location.file.includes("competitor-management") ? "competitor-management-e2e" : test.location.file.includes("product-management") ? "product-management-e2e" : test.location.file.includes("demand-prediction") ? "demand-prediction-e2e" : test.location.file.includes("dashboard-ingestion") ? "live-ai-ingestion" : test.location.file.includes("market-intelligence") ? "market-intelligence-e2e" : "authenticated-dashboard-e2e"),
      timestamp: new Date().toISOString(),
      durationMs: result.duration,
      tenantId: annotations.tenant || null,
      endpoint: annotations.api || null,
      status: skipped ? "BLOCKED" : result.status === "passed" ? "PASS" : result.status === "timedOut" || failureCategory === "TEST_ENVIRONMENT" ? "ERROR" : "FAIL",
      failureCategory,
      recommendedInvestigation: result.error ? this.recommend(String(failureCategory)) : null,
      metricChecks,
      uiMetrics,
      notes: annotations,
      error: result.error ? this.redact(result.error.message || "Test failed") : null,
      errors: result.errors?.map(error => this.redact(error.message || "Error")) || [],
      screenshot: result.attachments.find(item => item.name === "screenshot")?.path || null,
      trace: result.attachments.find(item => item.name === "trace")?.path || null
    });
  }

  onEnd() {
    const summary = {
      generatedAt: new Date().toISOString(),
      durationMs: Date.now() - this.startedAt,
      summary: Object.fromEntries(["PASS", "FAIL", "SKIP", "BLOCKED", "ERROR"].map(status => [status, this.rows.filter(row => row.status === status).length])),
      tests: this.rows
    };
    fs.mkdirSync(path.dirname(this.outputFile), { recursive: true });
    fs.writeFileSync(this.outputFile, JSON.stringify(summary, null, 2));
    for (const row of this.rows) console.log(`[${row.status}] ${row.test}${row.failureCategory ? ` — ${row.failureCategory}` : ""}`);
  }

  private classify(message: string) {
    if (/SMART_ALERT_(?:ENTITLEMENT|PLAN_ACCESS)/.test(message)) return "SMART_ALERT_ENTITLEMENT_BYPASS";
    if (/SMART_ALERT_(?:TENANT_ISOLATION|RLS)/.test(message)) return "SMART_ALERT_TENANT_ISOLATION_FAILURE";
    if (/SMART_ALERT_(?:DUPLICATE|IDEMPOTENCY)/.test(message)) return "SMART_ALERT_DUPLICATE_DELIVERY";
    if (/SMART_ALERT_(?:FALSE_SUCCESS|PREFERENCES)/.test(message)) return "SMART_ALERT_FALSE_SUCCESS_UI";
    if (/SMART_ALERT_(?:ACK|RESOLVE|LIFECYCLE)/.test(message)) return "SMART_ALERT_LIFECYCLE_UNAVAILABLE";
    if (/SMART_ALERT_(?:OUTBOX|DELIVERY|WORKER)/.test(message)) return "SMART_ALERT_DELIVERY_PATH_MISSING";
    if (/SMART_ALERT_(?:CURRENCY|FRESHNESS|STALE)/.test(message)) return "SMART_ALERT_PRICE_INTEGRITY";
    if (/SMART_ALERT_(?:RULE|CONFIG)/.test(message)) return "SMART_ALERT_RULES_UNAVAILABLE";
    if (/AI_PRICING_ENTITLEMENT|ai_pricing.*entitlement/i.test(message)) return "AI_PRICING_ENTITLEMENT_BYPASS";
    if (/AI_PRICING_QUOTA_RACE/.test(message)) return "AI_PRICING_QUOTA_RACE_CONDITION";
    if (/AI_PRICING_USAGE_NOT_CHARGED/.test(message)) return "AI_PRICING_USAGE_NOT_CHARGED";
    if (/AI_PRICING_QUOTA_EXCEEDED/.test(message)) return "AI_PRICING_QUOTA_EXCEEDED";
    if (/AI_PRICING_DUPLICATE_CHARGE/.test(message)) return "AI_PRICING_DUPLICATE_CHARGE";
    if (/AI_PRICING_BILLING_PERIOD/.test(message)) return "AI_PRICING_BILLING_PERIOD_ERROR";
    if (/AI_PRICING_COMPETITOR/.test(message)) return "AI_PRICING_COMPETITOR_SELECTION_ERROR";
    if (/AI_PRICING_FX_RATE_STALE/.test(message)) return "AI_PRICING_FX_RATE_STALE";
    if (/AI_PRICING_CURRENCY_MISMATCH/.test(message)) return "AI_PRICING_CURRENCY_MISMATCH";
    if (/AI_PRICING_FX/.test(message)) return "AI_PRICING_FX_RATE_INVALID";
    if (/AI_PRICING_MARKET_AVERAGE/.test(message)) return "AI_PRICING_MARKET_AVERAGE_ERROR";
    if (/AI_PRICING_THRESHOLD/.test(message)) return "AI_PRICING_THRESHOLD_ERROR";
    if (/AI_PRICING_GUARDRAIL_CONFLICT/.test(message)) return "AI_PRICING_GUARDRAIL_CONFLICT";
    if (/AI_PRICING_COST_FLOOR/.test(message)) return "AI_PRICING_COST_FLOOR_ERROR";
    if (/AI_PRICING_CONFIDENCE/.test(message)) return "AI_PRICING_CONFIDENCE_ERROR";
    if (/AI_PRICING_EVIDENCE/.test(message)) return "AI_PRICING_EVIDENCE_INCOMPLETE";
    if (/AI_PRICING_PERSISTENCE/.test(message)) return "AI_PRICING_PERSISTENCE_FAILURE";
    if (/AI_PRICING_DUPLICATE_RECOMMENDATION/.test(message)) return "AI_PRICING_DUPLICATE_RECOMMENDATION";
    if (/AI_PRICING_AI_CONTRACT/.test(message)) return "AI_PRICING_AI_CONTRACT_ERROR";
    if (/AI_PRICING_GRADIO/.test(message)) return "AI_PRICING_GRADIO_UNAVAILABLE";
    if (/AI_PRICING_FRONTEND_MISMATCH/.test(message)) return "AI_PRICING_FRONTEND_MISMATCH";
    if (/AI_PRICING_FALSE_SUCCESS/.test(message)) return "AI_PRICING_FALSE_SUCCESS_UI";
    if (/AI_PRICING_TENANT/.test(message)) return "AI_PRICING_TENANT_ISOLATION_FAILURE";
    if (/RECOMMENDATION_ENTITLEMENT_BYPASS/.test(message)) return "RECOMMENDATION_ENTITLEMENT_BYPASS";
    if (/RECOMMENDATION_AI_CONTRACT_ERROR/.test(message)) return "RECOMMENDATION_AI_CONTRACT_ERROR";
    if (/RECOMMENDATION_NODE_INTEGRATION_MISSING/.test(message)) return "RECOMMENDATION_NODE_INTEGRATION_MISSING";
    if (/RECOMMENDATION_FRONTEND_INTEGRATION_MISSING/.test(message)) return "RECOMMENDATION_FRONTEND_INTEGRATION_MISSING";
    if (/SALES_SOURCE_CONTRACT_MISMATCH/.test(message)) return "SALES_SOURCE_CONTRACT_MISMATCH";
    if (/RECOMMENDATION_SALES_CALCULATION_ERROR/.test(message)) return "RECOMMENDATION_SALES_CALCULATION_ERROR";
    if (/RECOMMENDATION_PRICE_GAP_ERROR/.test(message)) return "RECOMMENDATION_PRICE_GAP_ERROR";
    if (/RECOMMENDATION_CURRENCY_MISMATCH/.test(message)) return "RECOMMENDATION_CURRENCY_MISMATCH";
    if (/RECOMMENDATION_PRODUCT_MAPPING_ERROR/.test(message)) return "RECOMMENDATION_PRODUCT_MAPPING_ERROR";
    if (/RECOMMENDATION_SENTIMENT_ERROR/.test(message)) return "RECOMMENDATION_SENTIMENT_ERROR";
    if (/RECOMMENDATION_FORECAST_ERROR/.test(message)) return "RECOMMENDATION_FORECAST_ERROR";
    if (/RECOMMENDATION_THRESHOLD_ERROR/.test(message)) return "RECOMMENDATION_THRESHOLD_ERROR";
    if (/RECOMMENDATION_RANKING_ERROR/.test(message)) return "RECOMMENDATION_RANKING_ERROR";
    if (/RECOMMENDATION_EVIDENCE_MISSING/.test(message)) return "RECOMMENDATION_EVIDENCE_MISSING";
    if (/RECOMMENDATION_STALE_DATA/.test(message)) return "RECOMMENDATION_STALE_DATA";
    if (/RECOMMENDATION_FALSE_CAUSALITY/.test(message)) return "RECOMMENDATION_FALSE_CAUSALITY";
    if (/RECOMMENDATION_TENANT_ISOLATION_FAILURE/.test(message)) return "RECOMMENDATION_TENANT_ISOLATION_FAILURE";
    if (/RECOMMENDATION_DUPLICATE_OUTPUT/.test(message)) return "RECOMMENDATION_DUPLICATE_OUTPUT";
    if (/RECOMMENDATION_STATUS_INCORRECT/.test(message)) return "RECOMMENDATION_STATUS_INCORRECT";
    if (/RECOMMENDATION_FALSE_SUCCESS_UI/.test(message)) return "RECOMMENDATION_FALSE_SUCCESS_UI";
    if (/RECOMMENDATION_OUTCOME_TRACKING_UNAVAILABLE/.test(message)) return "RECOMMENDATION_OUTCOME_TRACKING_UNAVAILABLE";
    if (/TEST_ENVIRONMENT_BLOCKED/.test(message)) return "TEST_ENVIRONMENT_BLOCKED";
    if (/UPLOAD_VALIDATION_ERROR|invalid multipart|file upload/i.test(message)) return "UPLOAD_VALIDATION_ERROR";
    if (/DOCUMENT_QUOTA_EXCEEDED|document_extraction quota/i.test(message)) return "DOCUMENT_QUOTA_EXCEEDED";
    if (/SOURCE_LIMIT_BYPASS|connected_data_sources.*limit/i.test(message)) return "SOURCE_LIMIT_BYPASS";
    if (/CONNECTOR_NOT_OPERATIONAL|connector.*not operational/i.test(message)) return "CONNECTOR_NOT_OPERATIONAL";
    if (/CONNECTOR_AUTH_FAILURE|connector.*auth/i.test(message)) return "CONNECTOR_AUTH_FAILURE";
    if (/CONNECTOR_SYNC_FAILURE|connector.*sync/i.test(message)) return "CONNECTOR_SYNC_FAILURE";
    if (/CONNECTOR_CONFIGURATION_MISMATCH|source.*configuration/i.test(message)) return "CONNECTOR_CONFIGURATION_MISMATCH";
    if (/INGESTION_JOB_STUCK|job.*stuck|worker.*lease/i.test(message)) return "INGESTION_JOB_STUCK";
    if (/INGESTION_STAGING_FAILURE|staging.*failure/i.test(message)) return "INGESTION_STAGING_FAILURE";
    if (/INGESTION_PROMOTION_FAILURE|promotion.*failure/i.test(message)) return "INGESTION_PROMOTION_FAILURE";
    if (/INGESTION_DUPLICATE|duplicate.*import|idempotency/i.test(message)) return "INGESTION_DUPLICATE";
    if (/AI_RESPONSE_INVALID|malformed.*extraction/i.test(message)) return "AI_RESPONSE_INVALID";
    if (/AI_EXTRACTION_FAILURE|extraction.*unavailable/i.test(message)) return "AI_EXTRACTION_FAILURE";
    if (/SOURCE_STATUS_INCORRECT|FALSE_SUCCESS_UI|false.success|dataStatus.*verified/i.test(message)) return "FALSE_SUCCESS_UI";
    if (/CREDENTIAL_EXPOSURE|credential.*exposure|secret.*leak/i.test(message)) return "CREDENTIAL_EXPOSURE";
    if (/DOWNSTREAM_DATA_INCONSISTENCY|downstream.*(data|metric)/i.test(message)) return "DOWNSTREAM_DATA_INCONSISTENCY";
    if (/TEST_ENVIRONMENT_BLOCKED|disposable database.*configured/i.test(message)) return "TEST_ENVIRONMENT_BLOCKED";
    if (/COMPETITOR_NOT_PERSISTED|competitor.*not persisted/i.test(message)) return "COMPETITOR_NOT_PERSISTED";
    if (/COMPETITOR_LIMIT_BYPASS|tracked_competitors.*limit/i.test(message)) return "COMPETITOR_LIMIT_BYPASS";
    if (/DISCOVERY_TRIGGER_MISSING|discovery.*trigger/i.test(message)) return "DISCOVERY_TRIGGER_MISSING";
    if (/SOURCE_POLICY_VIOLATION|source policy/i.test(message)) return "SOURCE_POLICY_VIOLATION";
    if (/CURRENCY_MISMATCH|cross.currency/i.test(message)) return "CURRENCY_MISMATCH";
    if (/STALE_COMPETITOR_PRICE|stale competitor/i.test(message)) return "STALE_COMPETITOR_PRICE";
    if (/COMPETITOR_TRACKING_STATE_ERROR|untrack|reactivat/i.test(message)) return "COMPETITOR_TRACKING_STATE_ERROR";
    if (/CROSS_TENANT_DATA_EXPOSURE|cross.?tenant.*competitor/i.test(message)) return "CROSS_TENANT_DATA_EXPOSURE";
    if (/FRONTEND_PLACEHOLDER|preview.only competitor|industry filter/i.test(message)) return "FRONTEND_PLACEHOLDER";
    if (/BLOCKED_NOT_IMPLEMENTED|product CRUD|productsApi|product-management/i.test(message)) return "PRODUCT_CRUD_NOT_IMPLEMENTED";
    if (/success-shaped|frontend API stub|does not persist/i.test(message)) return "FRONTEND_API_STUB";
    if (/product.*not persisted|persist.*product/i.test(message)) return "PRODUCT_NOT_PERSISTED";
    if (/duplicate product|product matching|catalog match/i.test(message)) return "PRODUCT_MATCHING_ERROR";
    if (/product.*limit|tracked_products|capacity.*bypass/i.test(message)) return "PRODUCT_LIMIT_BYPASS";
    if (/price history|currency-only|price trigger/i.test(message)) return "PRICE_HISTORY_ERROR";
    if (/currency mismatch/i.test(message)) return "PRICE_CURRENCY_MISMATCH";
    if (/ingestion.*product|worker.*product/i.test(message)) return "INGESTION_PRODUCT_CONFLICT";
    if (/quick sale|invoice_item/i.test(message)) return "QUICK_SALE_NOT_PERSISTED";
    if (/soft.?delete|archive product/i.test(message)) return "PRODUCT_SOFT_DELETE_ERROR";
    if (/downstream.*product|product.*downstream/i.test(message)) return "DOWNSTREAM_DATA_INCONSISTENCY";
    if (/cross.?tenant.*product|product.*tenant isolation|price.history.*tenant/i.test(message)) return "TENANT_ISOLATION_FAILURE";
    if (/coverage.*partial|incomplete forecast/i.test(message)) return "FORECAST_COVERAGE_INCOMPLETE";
    if (/overlap|double count|duplicate forecast/i.test(message)) return "FORECAST_DUPLICATE";
    if (/horizon|period total|target.day/i.test(message)) return "FORECAST_HORIZON_MISMATCH";
    if (/AI response|malformed.*forecast|expected_demand/i.test(message)) return "AI_RESPONSE_INVALID";
    if (/model accuracy|MASE|model version/i.test(message)) return "MODEL_ACCURACY_UNAVAILABLE";
    if (/historical.*(missing|incomplete)|transaction history/i.test(message)) return "HISTORICAL_DATA_MISSING";
    if (/inventory.*(missing|stock)|safety stock/i.test(message)) return "INVENTORY_DATA_MISSING";
    if (/no forecast|no source rows|empty.*forecast/i.test(message)) return "INCORRECT_EMPTY_STATE";
    if (/cross.?tenant|tenant isolation|Tenant access denied/i.test(message)) return "TENANT_ISOLATION";
    if (/entitlement|subscription plan|feature access/i.test(message)) return "ENTITLEMENT_FAILURE";
    if (/pricing recommendation|AI pricing service|external service/i.test(message)) return "PRICING_RECOMMENDATION_FAILURE";
    if (/currency|exchange rate/i.test(message)) return "CURRENCY_MISMATCH";
    if (/stale|outdated|freshness/i.test(message)) return "STALE_MARKET_DATA";
    if (/competitor.*mapping|mapping.*missing/i.test(message)) return "COMPETITOR_MAPPING_MISSING";
    if (/scraper|market data producer|price observation/i.test(message)) return "SCRAPER_DATA_MISSING";
    if (/normaliz|composite score/i.test(message)) return "INCORRECT_SCORE_NORMALIZATION";
    if (/browserType\.launch|Executable doesn't exist|ECONNREFUSED|fetch failed|timed out|net::ERR/i.test(message)) return "TEST_ENVIRONMENT";
    if (/database|RLS|tenant context|postgres/i.test(message)) return "DATABASE_DATA_MISSING";
    if (/companies\/:companyId|HTTP|status.*200/i.test(message)) return "BACKEND_API";
    if (/locator|visible|text|toHaveText|heading|browser|pageerror/i.test(message)) return "FRONTEND_RENDERING";
    return "BACKEND_CALCULATION";
  }

  private recommend(category: string) {
    const recommendations: Record<string, string> = {
      UPLOAD_VALIDATION_ERROR: "Check multipart field, file signature, canonical template headers, configured size bound, and validation error mapping before AI/DB work.",
      DOCUMENT_QUOTA_EXCEEDED: "Compare rounded KB accounting, remaining entitlement, failure charging, storage usage, and concurrent reservation behavior for the tenant.",
      SOURCE_LIMIT_BYPASS: "Verify data_integration access and connected_data_sources capacity at the backend write boundary, including concurrent source creation.",
      CONNECTOR_NOT_OPERATIONAL: "Trace source registration through credential verification, approved scheduling, connector read, staging, and canonical business-table promotion.",
      CONNECTOR_AUTH_FAILURE: "Verify the connector credential-vault reference and provider authentication response without exposing the secret in logs.",
      CONNECTOR_SYNC_FAILURE: "Inspect the tenant-scoped sync job, source health, pagination/watermark state, retry policy, and last successful sync time.",
      CONNECTOR_CONFIGURATION_MISMATCH: "Compare frontend payload fields with validated/persisted connector configuration; verify URL and credentials are safely retained where the worker expects them.",
      INGESTION_JOB_STUCK: "Inspect job_status, processing_attempts, heartbeat_at, next_attempt_at, worker lease recovery, and pending row counts.",
      INGESTION_STAGING_FAILURE: "Compare AI extraction outcomes with tenant/job staging rows and validation statuses; never infer staging from upload HTTP success.",
      INGESTION_PROMOTION_FAILURE: "Compare committed staging references to independent tenant-scoped products and transactions and inspect the worker transaction result.",
      INGESTION_DUPLICATE: "Compare product matching keys and business transaction identifiers across source rows and retries; do not use product counts alone.",
      AI_RESPONSE_INVALID: "Compare the hosted extraction response with extractionResponseSchema and the strict Data Connections template/typed-field contract.",
      AI_EXTRACTION_FAILURE: "Inspect the Gradio service/API name, request context, timeout, upstream status, and sanitized integration error; keep extracted data out of logs.",
      FALSE_SUCCESS_UI: "Separate source registration, credential verification, synchronization, and completed persistence in both API state and UI messaging.",
      CREDENTIAL_EXPOSURE: "Inspect source response serializers, metadata validation, credential-vault boundaries, and redacted logs using a disposable sentinel only.",
      DOWNSTREAM_DATA_INCONSISTENCY: "Trace imported transactions/products into the specific Dashboard or Forecasting query; independently derive expected output from controlled tenant-owned rows.",
      TEST_ENVIRONMENT_BLOCKED: "Configure a named disposable migrated DB, authenticated test tenants, least-privilege worker role, and fixture cleanup before DB-mutating tests.",
      AI_PRICING_ENTITLEMENT_BYPASS: "Enforce the active tenant's ai_pricing allocation at the Node route before any provider request; keep standard plans ungranted.",
      AI_PRICING_QUOTA_EXCEEDED: "Check effective allocation, pre-call reservation, no-allocation behavior, failure charging policy, and tenant-wide usage across users.",
      AI_PRICING_USAGE_NOT_CHARGED: "Check whether a successful provider result has a durable usage allocation and whether missing usage is rejected or reconciled.",
      AI_PRICING_QUOTA_RACE_CONDITION: "Use an atomic tenant quota reservation and reconcile it with the final provider and persistence result under concurrent requests.",
      AI_PRICING_DUPLICATE_CHARGE: "Define retry and refresh billing semantics and enforce one idempotency key across provider work, evidence, outcomes, and usage.",
      AI_PRICING_BILLING_PERIOD_ERROR: "Compare usage reset boundaries with the active subscription billing period and test period transitions.",
      AI_PRICING_COMPETITOR_SELECTION_ERROR: "Select the latest eligible positive observation per active tracked mapping in product currency and the freshness window.",
      AI_PRICING_CURRENCY_MISMATCH: "Keep recommendation inputs in product currency; label converted cross-currency prices as reference only.",
      AI_PRICING_FX_RATE_INVALID: "Reject missing, nonpositive, inverted, or malformed exchange rates before conversion.",
      AI_PRICING_FX_RATE_STALE: "Apply an explicit exchange-rate freshness bound before conversion or provider submission.",
      AI_PRICING_MARKET_AVERAGE_ERROR: "Recompute the mean from the verified selected observation set and compare numerator, denominator, and currency.",
      AI_PRICING_THRESHOLD_ERROR: "Verify strict threshold comparisons at exact ±5% boundaries against the business policy.",
      AI_PRICING_GUARDRAIL_CONFLICT: "Document which safeguard wins when movement cap and cost floor conflict, then test that approved precedence.",
      AI_PRICING_COST_FLOOR_ERROR: "Confirm the 10% policy is a markup on cost and compare the suggestion with cost multiplied by 1.10.",
      AI_PRICING_CONFIDENCE_ERROR: "Validate confidence as a bounded heuristic score and label it so it is not shown as success probability.",
      AI_PRICING_EVIDENCE_INCOMPLETE: "Persist IDs and timestamps for every exact selected competitor observation and FX input used.",
      AI_PRICING_PERSISTENCE_FAILURE: "Verify evidence, outcome, and usage reservation behavior across transaction failures.",
      AI_PRICING_DUPLICATE_RECOMMENDATION: "Check request identity, retry behavior, uniqueness constraints, and recommendation history.",
      AI_PRICING_AI_CONTRACT_ERROR: "Compare the exact Gradio positional request and validated OK/UNKNOWN response with the Node schema.",
      AI_PRICING_GRADIO_UNAVAILABLE: "Check service routing, API name, bounded timeout, and sanitized provider failure mapping.",
      AI_PRICING_FRONTEND_MISMATCH: "Compare selected product, authenticated request, returned recommendation, persistence, and displayed currency/status.",
      AI_PRICING_FALSE_SUCCESS_UI: "Show availability and remaining credits from the backend and distinguish saved recommendations from local display state.",
      AI_PRICING_TENANT_ISOLATION_FAILURE: "Verify authenticated tenant scope in Node, tenant joins and RLS in PostgreSQL, and paired tenants under a restricted DB role.",
      RECOMMENDATION_ENTITLEMENT_BYPASS: "Verify the Node recommendation route checks the active subscription's business_recommendations boolean grant before calling AI.",
      RECOMMENDATION_AI_CONTRACT_ERROR: "Compare GET /dashboard/recommendations with the product_id/category/priority/message contract and reject malformed AI output at Node.",
      RECOMMENDATION_NODE_INTEGRATION_MISSING: "The AI endpoint exists but no customer-facing Node proxy is verified; define the contract and entitlement boundary before claiming workflow coverage.",
      RECOMMENDATION_FRONTEND_INTEGRATION_MISSING: "The legacy recommendation card is static and unused; connect a real authenticated API and truthful loading, empty, and error states.",
      SALES_SOURCE_CONTRACT_MISMATCH: "Reconcile transactions with invoices/invoice_items using an approved canonical source and idempotency policy; never add both sources blindly.",
      RECOMMENDATION_SALES_CALCULATION_ERROR: "Check invoice payment status, date bounds, returns, and source completeness before recomputing the 30-day trend.",
      RECOMMENDATION_PRICE_GAP_ERROR: "Check currency comparability, active/tracked mapping state, availability, observation freshness, and latest price selection.",
      RECOMMENDATION_CURRENCY_MISMATCH: "Compare like-currency prices only or apply an explicitly approved FX conversion; do not average JOD with USD.",
      RECOMMENDATION_PRODUCT_MAPPING_ERROR: "Verify tenant, product, competitor mapping, tracking, and active state before accepting competitor observations.",
      RECOMMENDATION_SENTIMENT_ERROR: "Verify review subject, product scope, tenant join, freshness, sentiment coverage, and business-wide fallback labeling.",
      RECOMMENDATION_FORECAST_ERROR: "Check forecast validity, version selection, units, horizon, and current sales-pace normalization.",
      RECOMMENDATION_THRESHOLD_ERROR: "Compare independent signal calculations to the configured threshold boundary; treat scores as heuristics.",
      RECOMMENDATION_RANKING_ERROR: "Compare rule priority, tie stability, limit behavior, and returned order with the actual internal ranking policy.",
      RECOMMENDATION_EVIDENCE_MISSING: "Only expose source rows, dates, freshness, and calculations present in the AI contract; do not fabricate evidence in Node/UI.",
      RECOMMENDATION_STALE_DATA: "Inspect observation and forecast timestamps, define freshness bounds, and suppress or label stale signals.",
      RECOMMENDATION_FALSE_CAUSALITY: "Keep competitor-price and sales relationships hedged as timing correlations unless causal evidence is separately established.",
      RECOMMENDATION_TENANT_ISOLATION_FAILURE: "Verify authenticated tenant, SQL predicates, forced RLS, and a non-superuser/non-BYPASSRLS role with paired test tenants.",
      RECOMMENDATION_DUPLICATE_OUTPUT: "Check rule deduplication, stable recommendation identity, and repeated source records before displaying duplicate cards.",
      RECOMMENDATION_STATUS_INCORRECT: "Compare computation and persistence state with UI status; do not label preview or generated-on-demand data as saved.",
      RECOMMENDATION_FALSE_SUCCESS_UI: "Keep UI loading/empty/error states truthful until a real tenant-entitled API result is returned.",
      RECOMMENDATION_OUTCOME_TRACKING_UNAVAILABLE: "Do not reuse recommendation_outcomes without an ownership decision; define lifecycle storage and retention first.",
      SMART_ALERT_ENTITLEMENT_BYPASS: "Define plan grants for system_alerts, then enforce the active subscription entitlement at every rule creation and delivery boundary while preserving essential billing notifications.",
      SMART_ALERT_TENANT_ISOLATION_FAILURE: "Verify tenant context, composite tenant keys, forced RLS, and recipient membership using two dedicated test tenants and a non-superuser/non-BYPASSRLS role.",
      SMART_ALERT_DUPLICATE_DELIVERY: "Define a stable tenant/rule/market-event dedupe key and enforce it transactionally across retries and concurrent workers.",
      SMART_ALERT_FALSE_SUCCESS_UI: "Connect preferences and alert controls to persisted APIs; represent unavailable, saved, and failed states truthfully in every locale.",
      SMART_ALERT_LIFECYCLE_UNAVAILABLE: "Add an authorized tenant-scoped alert lifecycle endpoint and keep acknowledgement/resolution distinct from inbox read/archive receipts.",
      SMART_ALERT_DELIVERY_PATH_MISSING: "Connect market_alert_events to the tenant notification transactional outbox and verify recipient selection, atomic delivery, retry, and failure states.",
      SMART_ALERT_PRICE_INTEGRITY: "Compare only like-currency observations ordered by event time, reject stale/late data, and persist event identity so retries cannot create duplicate alerts.",
      SMART_ALERT_RULES_UNAVAILABLE: "Implement tenant-scoped rule CRUD, supported metrics/operators, validation, plan access checks, and persisted preference state before enabling the settings UI.",
      COMPETITOR_NOT_PERSISTED: "Wire the Add Competitor form to competitorsApi.create and verify the returned tenant relationship after reload.",
      COMPETITOR_LIMIT_BYPASS: "Enforce competitor_management access and tracked_competitors capacity in a race-safe backend transaction for every write path.",
      DISCOVERY_TRIGGER_MISSING: "Trace Node upload through its hosted extraction provider and add/verify a discovery event only if the production contract requires it.",
      SOURCE_POLICY_VIOLATION: "Verify source policy state and approval evidence before collection is enqueued; retain source_status with each observation.",
      CURRENCY_MISMATCH: "Compare only same-currency prices or apply a documented exchange-rate contract; show unavailable when conversion is unsupported.",
      STALE_COMPETITOR_PRICE: "Expose observed_at and a defined freshness status before presenting saved observations as current prices.",
      COMPETITOR_TRACKING_STATE_ERROR: "Implement tenant relationship lifecycle endpoints while retaining observations and score history.",
      CROSS_TENANT_DATA_EXPOSURE: "Verify request tenant, composite joins, forced RLS, and a non-superuser role against two independently seeded tenants.",
      FRONTEND_PLACEHOLDER: "Connect the control to current API data and an implemented action or remove it from the interactive interface.",
      FRONTEND_RENDERING: "Inspect dashboard component state, selectors, locale formatting, and browser console errors.",
      PRODUCT_CRUD_NOT_IMPLEMENTED: "Product Management does not currently expose tenant product CRUD routes/pages. Add the real product service/UI path before enabling this E2E flow.",
      FRONTEND_API_STUB: "Replace the local success-shaped frontend function with the authenticated product API and verify the persisted row independently.",
      PRODUCT_NOT_PERSISTED: "Trace the request through the product controller/repository and verify a tenant-scoped row was committed.",
      PRODUCT_DUPLICATE: "Compare canonical product identity and import-job rows; inspect unique constraints and the import idempotency key.",
      PRODUCT_MATCHING_ERROR: "Inspect tenant-scoped name/SKU mapping, normalization, ambiguity handling, and import price ownership rules.",
      PRODUCT_LIMIT_BYPASS: "Enforce tracked_products server-side for manual and ingestion writes, including concurrent creates.",
      PRICE_HISTORY_ERROR: "Inspect the products price trigger and product_price_history rows for the tenant-scoped product.",
      PRICE_CURRENCY_MISMATCH: "Compare the old/new product currency with the price history and source transaction currency; do not infer FX conversion.",
      INGESTION_PRODUCT_CONFLICT: "Inspect import_staging_rows, the worker's product matching path, and the job's committed transaction rows.",
      PRODUCT_DATA_OVERWRITTEN: "Compare current product fields before and after import; imported sales should not silently overwrite curated catalog fields.",
      QUICK_SALE_NOT_PERSISTED: "Verify the frontend calls the authenticated AI quick-sale endpoint and check invoices/invoice_items plus Dashboard readers.",
      PRODUCT_SOFT_DELETE_ERROR: "Check deleted_at visibility policy and preserve invoice, transaction, inventory, forecast, and mapping relationships.",
      DOWNSTREAM_DATA_INCONSISTENCY: "Compare the same product ID across product, inventory, sales, forecast, competitor mapping, and dashboard sources.",
      TENANT_ISOLATION_FAILURE: "Verify the authenticated tenant and active membership context, composite tenant/product joins, and RLS role configuration.",
      FORECAST_HORIZON_MISMATCH: "Compare the AI output contract, requested horizon, stored interval, and whether expected_demand means a target-day value or a period total.",
      FORECAST_COVERAGE_INCOMPLETE: "Inspect daily target dates and gaps inside the requested UTC horizon; partial coverage must not be presented as a full total.",
      FORECAST_DUPLICATE: "Inspect competing forecast revisions and date-window overlap; apply the documented selection policy without double counting.",
      AI_RESPONSE_INVALID: "Inspect the analytics/forecast Gradio response schema and prevent malformed results from reaching persistence.",
      HISTORICAL_DATA_MISSING: "Check tenant-scoped transactions, product identity, ingestion status, date coverage, and model minimum-history rules.",
      MODEL_ACCURACY_UNAVAILABLE: "Check model_versions metadata, evaluation sample counts, model version references, and null-versus-zero accuracy handling.",
      INVENTORY_DATA_MISSING: "Check tenant-scoped warehouse positions, safety stock, and freshness before interpreting stock recommendations.",
      INCORRECT_EMPTY_STATE: "Check whether the UI distinguishes no data, partial coverage, and a verified numeric zero.",
      FRONTEND_FORMATTING: "Compare rendered number/date/currency formatting with the API payload and active locale.",
      BACKEND_CALCULATION: "Recompute the endpoint formula from the listed tenant tables and verify filters and UTC boundaries.",
      BACKEND_API: "Inspect dashboard controller/service logs and response status for this tenant and period.",
      DATABASE_DATA_MISSING: "Verify source rows, tenant/product relations, status fields, date coverage, currency, and RLS context.",
      DATABASE_RELATIONSHIP: "Check tenant-scoped foreign keys, joins, and producer linkage for the missing rows.",
      INGESTION_FAILURE: "Inspect upload response, staged row statuses, job error log, and ingestion worker logs.",
      AI_PIPELINE_UNAVAILABLE: "Check the configured AI extraction/forecast/sentiment provider and runtime health; no fallback is used.",
      ENTITLEMENT_FAILURE: "Check plan feature assignment and dashboard/demand-prediction access decisions.",
      TENANT_ISOLATION: "Verify token tenant, URL company ID, RLS context, and cross-tenant query filters.",
      PRICING_RECOMMENDATION_FAILURE: "Check the pricing client configuration, AI service health, request contract, and persisted evidence/outcome rows; the UI should not be blamed without a successful API response.",
      CURRENCY_MISMATCH: "Compare the product currency, eligible competitor currencies, exchange-rate inputs, and the API/UI format currency.",
      STALE_MARKET_DATA: "Check observed_at timestamps, source eligibility, collection schedule, and selected reporting period.",
      COMPETITOR_MAPPING_MISSING: "Check tenant_competitors and active competitor_product_mappings for this tenant/product.",
      SCRAPER_DATA_MISSING: "Check approved source policy, discovery/collection job state, and whether eligible competitor_prices rows were produced.",
      INCORRECT_SCORE_NORMALIZATION: "Compare latest competitor_score_snapshots values and units (0–100) with the API metric and UI denominator.",
      INCORRECT_EMPTY_STATE: "Check whether the API distinguishes no source rows from a populated series of zero values.",
      TEST_ENVIRONMENT: "Check server availability, test URLs, browser installation, and safe database configuration."
    };
    return recommendations[category] || "Compare the API result with independent database facts and inspect the corresponding dashboard code path.";
  }

  private redact(message: string) {
    return message
      .replace(/(Bearer\s+)[^\s"']+/gi, "$1[REDACTED]")
      .replace(/(postgres(?:ql)?:\/\/)[^\s"']+/gi, "$1[REDACTED]")
      .replace(/(password|secret|api[_-]?key|token)(\s*[=:]\s*)[^\s,"']+/gi, "$1$2[REDACTED]");
  }
}
