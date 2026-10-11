import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import test from "node:test";

const read = (file: string) => readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");

test("diagnostic: current product and Quick Sale UI clients still return local success-shaped stubs", () => {
  const productsApi = read("../frontend/src/features/products/api/productsApi.js");
  const quickSaleApi = read("../frontend/src/features/products/api/quickSaleApi.js");
  const inventoryApi = read("../frontend/src/features/products/api/inventoryApi.js");
  const form = read("../frontend/src/features/products/components/ProductForm.jsx");
  const table = read("../frontend/src/features/products/components/ProductTable.jsx");
  const quickSaleModal = read("../frontend/src/features/products/components/QuickSaleModal.jsx");
  const router = read("../frontend/src/app/router/index.jsx");

  assert.match(productsApi, /list:\s*async\s*\(\)\s*=>\s*\(\{\s*products:\s*\[\]\s*\}\)/);
  assert.match(productsApi, /getById:\s*async\s*\(id\)\s*=>\s*\(\{\s*id,\s*product:\s*null\s*\}\)/);
  assert.match(productsApi, /create:\s*async\s*\(payload\)\s*=>\s*\(\{\s*ok:\s*true,\s*payload\s*\}\)/);
  assert.match(productsApi, /update:\s*async\s*\(payload\)\s*=>\s*\(\{\s*ok:\s*true,\s*payload\s*\}\)/);
  assert.match(quickSaleApi, /sale:\s*async\s*\(payload\)\s*=>\s*\(\{\s*ok:\s*true,\s*payload\s*\}\)/);
  assert.match(inventoryApi, /levels:\s*async\s*\(\)\s*=>\s*\(\{\s*levels:\s*\[\]\s*\}\)/);
  assert.match(form, /Product Form/);
  assert.match(table, /Product Table/);
  assert.match(quickSaleModal, /Quick Sale/);
  assert.doesNotMatch(router, /ProductManagementPage|ProductListPage|ProductForm/);
});

test("product CRUD endpoints are not implemented in the backend module tree", () => {
  assert.equal(existsSync(new URL("../../src/modules/products", import.meta.url)), false);
  assert.equal(existsSync(new URL("../../src/modules/product-management", import.meta.url)), false);
});

test("product schema supports tenant-scoped price history and soft delete, with current trigger gaps preserved", () => {
  const schema = read("prisma/schema.prisma");
  const baseline = read("prisma/migrations/20260800000000_baseline/migration.sql");
  const productModel = schema.match(/model products \{[\s\S]*?\n\}/)?.[0] ?? "";
  const historyModel = schema.match(/model product_price_history \{[\s\S]*?\n\}/)?.[0] ?? "";
  const priceTrigger = baseline.match(/CREATE OR REPLACE FUNCTION trigger_log_price_change\(\)[\s\S]*?\$\$ LANGUAGE plpgsql;/)?.[0] ?? "";
  assert.match(productModel, /product_name\s+Json/);
  assert.match(productModel, /current_price\s+Decimal/);
  assert.match(productModel, /cost_price\s+Decimal\?/);
  assert.match(productModel, /currency\s+String/);
  assert.match(productModel, /deleted_at\s+DateTime\?/);
  assert.match(productModel, /@@unique\(\[tenant_id, product_id\]/);
  assert.match(historyModel, /old_price\s+Decimal\?/);
  assert.match(historyModel, /new_price\s+Decimal/);
  assert.match(historyModel, /@@index\(\[tenant_id, product_id, changed_at/);
  assert.match(baseline, /IF NEW\.current_price IS DISTINCT FROM OLD\.current_price THEN/);
  assert.match(baseline, /AFTER UPDATE ON products/);
  assert.ok(priceTrigger, "could not locate product price trigger");
  assert.doesNotMatch(priceTrigger, /NEW\.currency IS DISTINCT FROM OLD\.currency/);
});

test("tenant product RLS and relationship constraints protect identity and preserve invoice references", () => {
  const baseline = read("prisma/migrations/20260800000000_baseline/migration.sql");
  const schema = read("prisma/schema.prisma");
  assert.match(baseline, /ALTER TABLE products FORCE ROW LEVEL SECURITY/);
  assert.match(baseline, /CREATE POLICY select_products_isolated ON products FOR SELECT USING \(tenant_id = get_current_tenant\(\) AND deleted_at IS NULL\)/);
  assert.match(baseline, /CREATE POLICY isolation_price_history ON product_price_history FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
  assert.match(baseline, /FOREIGN KEY \(tenant_id, product_id\) REFERENCES products\(tenant_id, product_id\) ON DELETE RESTRICT/);
  assert.match(schema, /model inventory \{[\s\S]*?@@index\(\[tenant_id, product_id\]/);
  assert.doesNotMatch(schema.match(/model inventory \{[\s\S]*?\n\}/)?.[0] ?? "", /@@unique\(\[tenant_id, product_id\]/);
  assert.match(schema, /model transactions \{[\s\S]*?products\s+products\s+@relation\(fields: \[tenant_id, product_id\]/);
  assert.match(schema, /model competitor_product_mappings \{[\s\S]*?products\s+products\s+@relation\(fields: \[tenant_id, product_id\]/);
  assert.match(schema, /model demand_forecasts \{[\s\S]*?products\s+products\s+@relation\(fields: \[tenant_id, product_id\]/);
});

test("standard plan product entitlements match configured limits; imported product path has no capacity gate", () => {
  const plans = read("src/config/production-plans.ts");
  const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
  const capacity = read("src/modules/features/service/capacity.service.ts");
  assert.match(plans, /booleanFeature\("product_management"\)[\s\S]{0,300}limitFeature\("tracked_products", 250\)/);
  assert.match(plans, /booleanFeature\("product_management"\)[\s\S]{0,500}limitFeature\("tracked_products", 2_000\)/);
  assert.match(plans, /booleanFeature\("product_management"\)[\s\S]{0,500}limitFeature\("tracked_products", 10_000\)/);
  assert.match(capacity, /case "tracked_products":[\s\S]*?prisma\.products\.count\([\s\S]*?deleted_at: null/);
  const ensureProduct = worker.match(/async function ensureImportedProduct\([\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(ensureProduct, "could not locate worker product resolver");
  assert.doesNotMatch(ensureProduct, /tracked_products|assertFeatureCapacity|assertUsage|capacity/i);
});

test("import matching is serialized per tenant and English name, preserves existing price, and has no stable SKU key", () => {
  const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
  const schema = read("prisma/schema.prisma");
  const ensureProduct = worker.match(/async function ensureImportedProduct\([\s\S]*?\n\}/)?.[0] ?? "";
  const productModel = schema.match(/model products \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.match(ensureProduct, /productName\.trim\(\)\.toLocaleLowerCase\("en-US"\)/);
  assert.match(ensureProduct, /pg_advisory_xact_lock/);
  assert.match(ensureProduct, /p\.product_name ->> 'en'/);
  assert.match(ensureProduct, /if \(existingId\)[\s\S]*?return existingId/);
  const existingMatchBranch = ensureProduct.match(/if \(existingId\) \{([\s\S]*?)\n  \}/)?.[1] ?? "";
  assert.match(existingMatchBranch, /return existingId/);
  assert.doesNotMatch(existingMatchBranch, /products\.update|unitPrice/);
  assert.doesNotMatch(productModel, /\b(?:sku|external_product_id|external_id)\b/i);
});

test("upload route separates extraction/queueing from worker promotion and deduplication evidence", () => {
  const route = read("src/modules/dataconnection/route/dataconnection.route.ts");
  const controller = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
  const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
  const migration = read("prisma/migrations/20261006120000_business_data_ingestion_worker/migration.sql");
  assert.match(route, /router\.post\([\s\S]*?requireEntitlement\("document_extraction"\)[\s\S]*?upload\.single\("file"\)[\s\S]*?validateFile/);
  assert.match(controller, /status\(200\)[\s\S]*?Document extracted and queued for import/);
  assert.match(worker, /validation_status: "PENDING"/);
  assert.match(worker, /validation_status: "COMMITTED"/);
  assert.match(worker, /INSERT INTO transactions|transactions\.create/);
  assert.match(migration, /GRANT SELECT, INSERT ON TABLE products TO ceopro_ingestion_worker/);
  assert.doesNotMatch(migration, /tracked_products|assertFeatureCapacity|capacity/i);
  assert.doesNotMatch(worker, /file_hash|content_hash|duplicate.*job|idempotency_key/i);
});

test("Quick Sale has a separate authenticated AI persistence path, while UI wiring and request safeguards are missing", () => {
  const main = read("../ai/src/ai/main.py");
  const quickSale = read("../ai/src/ai/sales/quick_sale.py");
  const clientTests = read("../ai/src/ai/tests/test_main.py");
  const quickSaleRequest = main.match(/class QuickSaleRequest\(BaseModel\):[\s\S]*?\n\nclass AddCompetitorRequest/)?.[0] ?? "";
  assert.match(main, /@app\.post\("\/sales\/quick-sale"\)/);
  assert.match(main, /ctx: TenantContext = Depends\(get_tenant_context\)/);
  assert.match(main, /quick_sale\.record_quick_sale\([\s\S]*?ctx\.tenant_id[\s\S]*?ctx\.user_id/);
  assert.match(quickSale, /INSERT INTO invoices/);
  assert.match(quickSale, /INSERT INTO invoice_items/);
  assert.match(quickSale, /deleted_at IS NULL/);
  assert.match(clientTests, /test_quick_sale_returns_the_pipeline_result/);
  assert.ok(quickSaleRequest, "could not locate Quick Sale request model");
  assert.match(quickSaleRequest, /quantity:\s*int/);
  assert.match(quickSaleRequest, /unit_price:\s*Optional\[float\]/);
  assert.doesNotMatch(quickSaleRequest, /Field\(|field_validator|gt=|ge=/);
  assert.doesNotMatch(quickSale, /idempotency|ON CONFLICT/);
  const frontend = read("../frontend/src/features/products/api/quickSaleApi.js");
  assert.match(frontend, /ok:\s*true,\s*payload/);
  assert.doesNotMatch(frontend, /fetch\(|axios|quick-sale/);
  assert.doesNotMatch(quickSale, /UPDATE inventory|INSERT INTO inventory/);
});

test("AI FastAPI extraction promotion is a separate product writer with the same name-based price preservation and no capacity gate", () => {
  const promotion = read("../ai/src/ai/extraction/promotion.py");
  const main = read("../ai/src/ai/main.py");
  assert.match(main, /@app\.post\("\/extraction\/upload"\)/);
  assert.match(main, /promote_ingested_rows/);
  assert.match(promotion, /SELECT product_id, product_name->>'en' FROM products/);
  assert.match(promotion, /name\.strip\(\)\.casefold\(\)/);
  assert.match(promotion, /Never touches an\s+existing product's current_price\/currency/);
  assert.match(promotion, /INSERT INTO products/);
  assert.match(promotion, /INSERT INTO transactions/);
  assert.doesNotMatch(promotion, /tracked_products|assertFeatureCapacity|capacity/i);
  assert.doesNotMatch(promotion, /ON CONFLICT|idempotency_key|source_row_id/);
});

test("shared Product Management database diagnostics stay read-only and enforce RLS-capable roles", () => {
  const database = read("tests/support/diagnostics/dashboard-db.ts");
  const method = database.match(/async getProductManagementFacts\([\s\S]*?\n  \}\n\n  async close/)?.[0] ?? "";
  assert.ok(method, "read-only Product Management snapshot method is missing");
  assert.match(method, /BEGIN READ ONLY/);
  assert.match(method, /setTenantContext\(client, tenantId, userId\)/);
  assert.match(method, /rolsuper \|\| roleCheck\.rows\[0\]\.rolbypassrls/);
  assert.match(method, /products[\s\S]*?product_price_history[\s\S]*?inventory[\s\S]*?transactions[\s\S]*?invoice_items[\s\S]*?demand_forecasts[\s\S]*?competitor_product_mappings/);
  assert.match(database, /database whose name clearly identifies it as test, qa, or e2e/);
  assert.doesNotMatch(method, /\b(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP)\s+\w+/i);
});

test("shared Playwright diagnostics preserve Product Management categories on blocked tests", () => {
  const reporter = read("tests/support/diagnostics/dashboard-reporter.ts");
  const suite = read("tests/e2e/product-management/product-management.spec.ts");
  assert.match(reporter, /test\.location\.file\.includes\("product-management"\).*product-management-e2e/);
  assert.match(reporter, /const failureCategory = annotations\["failure-category"\]/);
  assert.match(reporter, /skipped \? "BLOCKED"/);
  assert.match(reporter, /PRODUCT_CRUD_NOT_IMPLEMENTED/);
  assert.match(reporter, /PRODUCT_LIMIT_BYPASS/);
  assert.match(reporter, /TENANT_ISOLATION_FAILURE/);
  assert.match(suite, /testInfo\.skip\(true, `BLOCKED_NOT_IMPLEMENTED:/);
  assert.match(suite, /type: "expected"/);
  assert.match(suite, /type: "actual"/);
  assert.match(suite, /type: "recommended-investigation"/);
  assert.doesNotMatch(suite, /page\.route|mocked|route\.fulfill/);
});
