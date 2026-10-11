import { Pool, type PoolClient } from "pg";

export type DashboardDbFacts = {
  tenantId: string;
  currency: string;
  productCount: number;
  paidInvoiceCount: number;
  revenue: number;
  previousRevenue: number;
  inventory: { inStock: number; lowStock: number; outOfStock: number; total: number };
  trackedCompetitors: number;
  sentimentAverage: number | null;
  qualifyingReviews: number;
  invoiceCurrencyExcluded: number;
  dateRange: { start: string; endExclusive: string; previousStart: string };
};
export type IngestionSnapshot = { status: string; rowsProcessed: number; rowsFailed: number; stagingTotal: number; stagingCommitted: number; stagingPending: number; stagingInvalid: number };
export type MarketCompetitorFact = {
  competitorId: string;
  latestPrice: number | null;
  previousPrice: number | null;
  latestPriceCurrency: string | null;
  pricingScore: number | null;
  compositeScore: number | null;
  priceObservedAt: string | null;
};
export type MarketIntelligenceFacts = {
  tenantId: string;
  productId: string;
  productPrice: number;
  currency: string;
  competitorRows: MarketCompetitorFact[];
  totalCompetitors: number;
  averagePriceScore: number | null;
  averageCompositeScore: number | null;
};
export type PricingPersistenceFacts = { evidenceId: string | null; outcomeId: string | null; evidenceStored: boolean; outcomeStored: boolean };
export type DemandForecastFact = {
  forecastId: string;
  productId: string;
  startDate: string | null;
  endDate: string | null;
  targetDate: string | null;
  expectedDemand: number;
  lowerBound: number | null;
  upperBound: number | null;
  modelVersion: string;
  createdAt: string | null;
  features: unknown;
};
export type DemandPredictionFacts = {
  tenantId: string;
  products: Array<{ productId: string; name: unknown; category: unknown }>;
  forecasts: DemandForecastFact[];
  inventory: Array<{ productId: string; stock: number; safetyStock: number | null }>;
  sales: Array<{ productId: string; date: string; units: number }>;
};
export type ForecastPersistenceFacts = { forecastStored: boolean; evidenceStored: boolean; tenantId: string; productId: string };
export type ProductManagementFacts = {
  tenantId: string;
  productId: string | null;
  products: Array<{ productId: string; name: unknown; category: unknown; currentPrice: number; costPrice: number | null; currency: string; source: string; deletedAt: string | null }>;
  priceHistory: Array<{ productId: string; oldPrice: number | null; newPrice: number; currency: string; changedAt: string | null }>;
  inventory: Array<{ productId: string; stock: number; reorderLevel: number; safetyStock: number; warehouse: string | null }>;
  transactions: Array<{ transactionId: string; productId: string; quantity: number; unitPrice: number; totalPrice: number; currency: string; saleSource: string; transactionDate: string }>;
  invoiceItems: Array<{ invoiceId: string; productId: string; quantity: number; unitPrice: number; totalPrice: number; currency: string; paymentStatus: string }>;
  forecasts: Array<{ forecastId: string; productId: string; expectedDemand: number; startDate: string | null; endDate: string | null }>;
  competitorMappings: Array<{ mappingId: string; productId: string; isActive: boolean }>;
};

function safeDatabaseName(connectionString: string): string {
  if (process.env.NODE_ENV === "production") throw new Error("Dashboard diagnostics refuse to run with NODE_ENV=production.");
  const name = new URL(connectionString).pathname.replace(/^\//, "").toLowerCase();
  if (!/(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(name)) {
    throw new Error("DASHBOARD_TEST_DATABASE_URL must point to a database whose name clearly identifies it as test, qa, or e2e.");
  }
  return name;
}

export class DashboardDatabase {
  private readonly pool: Pool;

  constructor(connectionString: string) {
    safeDatabaseName(connectionString);
    this.pool = new Pool({ connectionString, max: 1, connectionTimeoutMillis: 5_000, application_name: "ceopro-dashboard-diagnostics" });
  }

  async getFacts(tenantId: string, userId: string, periodDays: number): Promise<DashboardDbFacts> {
    if (!/^\d{1,3}$/.test(String(periodDays)) || ![7, 30, 90].includes(periodDays)) throw new Error("Unsupported dashboard period.");
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
      );
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) {
        throw new Error("Dashboard verification requires a non-superuser database role without BYPASSRLS.");
      }

      const facts = await readFacts(client, tenantId, periodDays);
      await client.query("COMMIT");
      return facts;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async getIngestionSnapshot(tenantId: string, userId: string, jobId: string): Promise<IngestionSnapshot | null> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const job = await client.query<{ job_status: string; rows_processed: number | null; rows_failed: number | null }>(
        "SELECT job_status, rows_processed, rows_failed FROM ingestion_jobs WHERE tenant_id = $1 AND job_id = $2", [tenantId, jobId]);
      if (!job.rows[0]) { await client.query("COMMIT"); return null; }
      const rows = await client.query<{ total: string; committed: string; pending: string; invalid: string }>(
        `SELECT count(*) AS total,
                count(*) FILTER (WHERE validation_status = 'COMMITTED') AS committed,
                count(*) FILTER (WHERE validation_status = 'PENDING') AS pending,
                count(*) FILTER (WHERE validation_status = 'INVALID') AS invalid
           FROM import_staging_rows WHERE tenant_id = $1 AND job_id = $2`, [tenantId, jobId]);
      await client.query("COMMIT");
      const row = rows.rows[0]!;
      return { status: job.rows[0].job_status, rowsProcessed: job.rows[0].rows_processed || 0, rowsFailed: job.rows[0].rows_failed || 0,
        stagingTotal: Number(row.total), stagingCommitted: Number(row.committed), stagingPending: Number(row.pending), stagingInvalid: Number(row.invalid) };
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  /**
   * Read-only, RLS-scoped source facts used to independently check the
   * Market Intelligence overview. The SQL deliberately mirrors the source
   * eligibility rules, while the score averages are calculated in TypeScript.
   */
  async getMarketIntelligenceFacts(tenantId: string, userId: string, productId: string, periodDays: number): Promise<MarketIntelligenceFacts> {
    if (!/^\d{1,3}$/.test(String(periodDays)) || ![30, 90].includes(periodDays)) throw new Error("Unsupported Market Intelligence period.");
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
      );
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) {
        throw new Error("Market Intelligence verification requires a non-superuser database role without BYPASSRLS.");
      }
      const product = await client.query<{ product_id: string; current_price: string; currency: string }>(
        "SELECT product_id, current_price::text, currency FROM products WHERE tenant_id = $1 AND product_id = $2 AND deleted_at IS NULL",
        [tenantId, productId]
      );
      if (!product.rows[0]) throw new Error("Selected product is unavailable under the configured tenant context (or RLS denied access).");
      const result = await client.query<{
        competitor_id: string; latest_price: string | null; previous_price: string | null;
        latest_currency: string | null; composite_score: string | null; observed_at: Date | null;
      }>(
        `SELECT m.global_competitor_id AS competitor_id,
                price.latest_price, price.previous_price, price.latest_currency,
                score.composite_score, price.observed_at
           FROM competitor_product_mappings m
           JOIN tenant_competitors tc
             ON tc.tenant_id = m.tenant_id AND tc.global_competitor_id = m.global_competitor_id
           LEFT JOIN LATERAL (
             SELECT (array_agg(cp.scraped_price::text ORDER BY cp.observed_at DESC))[1] AS latest_price,
                    (array_agg(cp.scraped_price::text ORDER BY cp.observed_at DESC))[2] AS previous_price,
                    (array_agg(cp.currency ORDER BY cp.observed_at DESC))[1] AS latest_currency,
                    max(cp.observed_at) AS observed_at
               FROM competitor_prices cp
              WHERE cp.tenant_id = m.tenant_id AND cp.mapping_id = m.mapping_id
                AND cp.is_available = TRUE AND cp.is_exact_data = TRUE
                AND cp.source_status = 'ALLOWED' AND cp.currency = $4
                AND cp.observed_at >= now() - ($3::int * interval '1 day') AND cp.observed_at <= now()
           ) price ON TRUE
           LEFT JOIN LATERAL (
             SELECT s.composite_score::text AS composite_score
               FROM competitor_score_snapshots s
              WHERE s.tenant_id = m.tenant_id AND s.global_competitor_id = m.global_competitor_id
              ORDER BY s.calculated_at DESC, s.score_id DESC LIMIT 1
           ) score ON TRUE
          WHERE m.tenant_id = $1 AND m.product_id = $2 AND m.is_active = TRUE AND tc.is_tracked = TRUE
          ORDER BY m.mapping_id`,
        [tenantId, productId, periodDays, product.rows[0].currency]
      );
      const currentPrice = Number(product.rows[0].current_price);
      const competitorRows = result.rows.map((row) => {
        const latest = row.latest_price == null ? null : Number(row.latest_price);
        const score = latest == null || !Number.isFinite(latest) || currentPrice <= 0 || latest <= 0
          ? null
          : Math.max(0, Math.min(10, 10 - Math.abs(1 - currentPrice / latest) * 10));
        return {
          competitorId: row.competitor_id,
          latestPrice: latest,
          previousPrice: row.previous_price == null ? null : Number(row.previous_price),
          latestPriceCurrency: row.latest_currency,
          pricingScore: score == null ? null : Number(score.toFixed(1)),
          compositeScore: row.composite_score == null ? null : Number(row.composite_score),
          priceObservedAt: row.observed_at?.toISOString() ?? null
        };
      });
      const averageOf = (values: Array<number | null>) => {
        const eligible = values.filter((value): value is number => value !== null && Number.isFinite(value));
        return eligible.length ? eligible.reduce((sum, value) => sum + value, 0) / eligible.length : null;
      };
      const facts = {
        tenantId,
        productId,
        productPrice: currentPrice,
        currency: product.rows[0].currency,
        competitorRows,
        totalCompetitors: competitorRows.length,
        averagePriceScore: averageOf(competitorRows.map((row) => row.pricingScore)),
        averageCompositeScore: averageOf(competitorRows.map((row) => row.compositeScore))
      };
      await client.query("COMMIT");
      return facts;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally { client.release(); }
  }

  async getPricingPersistenceFacts(tenantId: string, userId: string, evidenceId: string | null, outcomeId: string | null): Promise<PricingPersistenceFacts> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user");
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) throw new Error("Market Intelligence verification requires a non-superuser database role without BYPASSRLS.");
      const [evidence, outcome] = await Promise.all([
        evidenceId ? client.query("SELECT 1 FROM evidence_records WHERE tenant_id = $1 AND evidence_id = $2", [tenantId, evidenceId]) : Promise.resolve({ rows: [] }),
        outcomeId ? client.query("SELECT 1 FROM recommendation_outcomes WHERE tenant_id = $1 AND recommendation_id = $2", [tenantId, outcomeId]) : Promise.resolve({ rows: [] })
      ]);
      await client.query("COMMIT");
      return { evidenceId, outcomeId, evidenceStored: evidence.rows.length === 1, outcomeStored: outcome.rows.length === 1 };
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  /** Read the forecast source rows under RLS for independent test calculations. */
  async getDemandPredictionFacts(tenantId: string, userId: string, startDate: string, periodDays: number, productId = "all"): Promise<DemandPredictionFacts> {
    if (![7, 30].includes(periodDays) || !/^\d{4}-\d{2}-\d{2}$/.test(startDate)) throw new Error("Unsupported Demand Prediction period or date.");
    const start = new Date(`${startDate}T00:00:00.000Z`);
    if (!Number.isFinite(start.getTime()) || start.toISOString().slice(0, 10) !== startDate) throw new Error("Invalid Demand Prediction UTC start date.");
    const end = new Date(start.getTime() + (periodDays - 1) * 86_400_000);
    const priorStart = new Date(start.getTime() - periodDays * 86_400_000);
    const historyStart = new Date(start.getTime() - 365 * 86_400_000);
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user");
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) throw new Error("Demand Prediction verification requires a non-superuser database role without BYPASSRLS.");
      const productClause = productId === "all" ? "" : " AND p.product_id = $2::uuid";
      const productParams = productId === "all" ? [tenantId] : [tenantId, productId];
      const products = await client.query<{ product_id: string; product_name: unknown; category: unknown }>(
        `SELECT p.product_id, p.product_name, p.category FROM products p WHERE p.tenant_id = $1 AND p.deleted_at IS NULL${productClause} ORDER BY p.product_id`, productParams
      );
      const inventory = await client.query<{ product_id: string; stock_quantity: string; safety_stock: string | null }>(
        `SELECT i.product_id, i.stock_quantity::text, i.safety_stock::text FROM inventory i JOIN products p ON p.tenant_id = i.tenant_id AND p.product_id = i.product_id WHERE i.tenant_id = $1 AND p.deleted_at IS NULL${productClause} ORDER BY i.product_id`, productParams
      );
      const forecastParams = productId === "all" ? [tenantId, priorStart, end] : [tenantId, productId, priorStart, end];
      const forecastProductClause = productId === "all" ? "" : " AND f.product_id = $2::uuid";
      const dateParamOffset = productId === "all" ? 2 : 3;
      const forecasts = await client.query<{
        forecast_id: string; product_id: string; forecast_start_date: string | null; forecast_end_date: string | null; forecast_target_date: string | null;
        expected_demand: string; confidence_range_lower: string | null; confidence_range_upper: string | null; model_version: string; created_at: Date | null; features_used: unknown;
      }>(
        `SELECT f.forecast_id, f.product_id, f.forecast_start_date::text, f.forecast_end_date::text, f.forecast_target_date::text,
                f.expected_demand::text, f.confidence_range_lower::text, f.confidence_range_upper::text,
                f.model_version, f.created_at, f.features_used
           FROM demand_forecasts f JOIN products p ON p.tenant_id = f.tenant_id AND p.product_id = f.product_id
          WHERE f.tenant_id = $1 AND p.deleted_at IS NULL${forecastProductClause}
            AND ((f.forecast_start_date <= $${dateParamOffset + 1}::date AND f.forecast_end_date >= $${dateParamOffset}::date)
                 OR (f.forecast_start_date IS NULL AND f.forecast_end_date IS NULL AND f.forecast_target_date BETWEEN $${dateParamOffset}::date AND $${dateParamOffset + 1}::date))
          ORDER BY f.product_id, f.created_at DESC NULLS LAST, f.forecast_id DESC`, forecastParams
      );
      const sales = await client.query<{ product_id: string; date: string; units: string }>(
        `SELECT t.product_id, to_char(t.transaction_date AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date,
                SUM(t.quantity_sold)::text AS units
           FROM transactions t JOIN products p ON p.tenant_id = t.tenant_id AND p.product_id = t.product_id
          WHERE t.tenant_id = $1 AND p.deleted_at IS NULL AND t.transaction_date >= $2 AND t.transaction_date < $3${productId === "all" ? "" : " AND t.product_id = $4::uuid"}
          GROUP BY t.product_id, 2 ORDER BY t.product_id, 2`,
        productId === "all" ? [tenantId, historyStart, new Date(end.getTime() + 86_400_000)] : [tenantId, historyStart, new Date(end.getTime() + 86_400_000), productId]
      );
      await client.query("COMMIT");
      return {
        tenantId,
        products: products.rows.map(row => ({ productId: row.product_id, name: row.product_name, category: row.category })),
        forecasts: forecasts.rows.map(row => ({ forecastId: row.forecast_id, productId: row.product_id, startDate: row.forecast_start_date, endDate: row.forecast_end_date, targetDate: row.forecast_target_date, expectedDemand: Number(row.expected_demand), lowerBound: row.confidence_range_lower == null ? null : Number(row.confidence_range_lower), upperBound: row.confidence_range_upper == null ? null : Number(row.confidence_range_upper), modelVersion: row.model_version, createdAt: row.created_at?.toISOString() ?? null, features: row.features_used })),
        inventory: inventory.rows.map(row => ({ productId: row.product_id, stock: Number(row.stock_quantity), safetyStock: row.safety_stock == null ? null : Number(row.safety_stock) })),
        sales: sales.rows.map(row => ({ productId: row.product_id, date: row.date, units: Number(row.units) }))
      };
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  async getForecastPersistenceFacts(tenantId: string, userId: string, productId: string, forecastId: string, evidenceId: string): Promise<ForecastPersistenceFacts> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user");
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) throw new Error("Demand Prediction verification requires a non-superuser database role without BYPASSRLS.");
      const forecast = await client.query("SELECT 1 FROM demand_forecasts WHERE tenant_id = $1 AND product_id = $2 AND forecast_id = $3", [tenantId, productId, forecastId]);
      const evidence = await client.query("SELECT 1 FROM evidence_records WHERE tenant_id = $1 AND forecast_id = $2 AND evidence_id = $3", [tenantId, forecastId, evidenceId]);
      await client.query("COMMIT");
      return { forecastStored: forecast.rows.length === 1, evidenceStored: evidence.rows.length === 1, tenantId, productId };
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  /** Read Product Management and downstream relationships under the caller's active RLS context. */
  async getProductManagementFacts(tenantId: string, userId: string, productId: string | null = null): Promise<ProductManagementFacts> {
    if (productId !== null && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(productId)) {
      throw new Error("Product Management verification requires a UUID product ID.");
    }
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ ONLY");
      await setTenantContext(client, tenantId, userId);
      const roleCheck = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user");
      if (!roleCheck.rows[0] || roleCheck.rows[0].rolsuper || roleCheck.rows[0].rolbypassrls) {
        throw new Error("Product Management verification requires a non-superuser database role without BYPASSRLS.");
      }
      const params = productId === null ? [tenantId] : [tenantId, productId];
      const clause = productId === null ? "" : " AND product_id = $2::uuid";
      const [products, priceHistory, inventory, transactions, invoiceItems, forecasts, mappings] = await Promise.all([
        client.query<{ product_id: string; product_name: unknown; category: unknown; current_price: string; cost_price: string | null; currency: string; source: string; deleted_at: Date | null }>(
          `SELECT product_id, product_name, category, current_price::text, cost_price::text, currency, source, deleted_at FROM products WHERE tenant_id = $1${clause} ORDER BY product_id`, params),
        client.query<{ product_id: string; old_price: string | null; new_price: string; currency: string; changed_at: Date | null }>(
          `SELECT product_id, old_price::text, new_price::text, currency, changed_at FROM product_price_history WHERE tenant_id = $1${clause} ORDER BY changed_at, price_history_id`, params),
        client.query<{ product_id: string; stock_quantity: number; reorder_level: number; safety_stock: number; warehouse_location: string | null }>(
          `SELECT product_id, stock_quantity, reorder_level, safety_stock, warehouse_location FROM inventory WHERE tenant_id = $1${clause} ORDER BY product_id, inventory_id`, params),
        client.query<{ transaction_id: string; product_id: string; quantity_sold: number; unit_price: string; total_price: string; original_currency: string; sale_source: string; transaction_date: Date }>(
          `SELECT transaction_id, product_id, quantity_sold, unit_price::text, total_price::text, original_currency, sale_source, transaction_date FROM transactions WHERE tenant_id = $1${clause} ORDER BY transaction_date, transaction_id`, params),
        client.query<{ invoice_id: string; product_id: string; quantity: number; unit_price: string; total_price: string; currency: string; payment_status: string }>(
          `SELECT i.invoice_id, ii.product_id, ii.quantity, ii.unit_price::text, ii.total_price::text, i.currency, i.payment_status FROM invoice_items ii JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id WHERE ii.tenant_id = $1${clause.replaceAll("product_id", "ii.product_id")} ORDER BY i.issue_date, i.invoice_id`, params),
        client.query<{ forecast_id: string; product_id: string; expected_demand: string; forecast_start_date: string | null; forecast_end_date: string | null }>(
          `SELECT forecast_id, product_id, expected_demand::text, forecast_start_date::text, forecast_end_date::text FROM demand_forecasts WHERE tenant_id = $1${clause} ORDER BY created_at, forecast_id`, params),
        client.query<{ mapping_id: string; product_id: string; is_active: boolean }>(
          `SELECT mapping_id, product_id, is_active FROM competitor_product_mappings WHERE tenant_id = $1${clause} ORDER BY mapping_id`, params)
      ]);
      await client.query("COMMIT");
      return {
        tenantId,
        productId,
        products: products.rows.map(row => ({ productId: row.product_id, name: row.product_name, category: row.category, currentPrice: Number(row.current_price), costPrice: row.cost_price === null ? null : Number(row.cost_price), currency: row.currency, source: row.source, deletedAt: row.deleted_at?.toISOString() ?? null })),
        priceHistory: priceHistory.rows.map(row => ({ productId: row.product_id, oldPrice: row.old_price === null ? null : Number(row.old_price), newPrice: Number(row.new_price), currency: row.currency, changedAt: row.changed_at?.toISOString() ?? null })),
        inventory: inventory.rows.map(row => ({ productId: row.product_id, stock: row.stock_quantity, reorderLevel: row.reorder_level, safetyStock: row.safety_stock, warehouse: row.warehouse_location })),
        transactions: transactions.rows.map(row => ({ transactionId: row.transaction_id, productId: row.product_id, quantity: row.quantity_sold, unitPrice: Number(row.unit_price), totalPrice: Number(row.total_price), currency: row.original_currency, saleSource: row.sale_source, transactionDate: row.transaction_date.toISOString() })),
        invoiceItems: invoiceItems.rows.map(row => ({ invoiceId: row.invoice_id, productId: row.product_id, quantity: row.quantity, unitPrice: Number(row.unit_price), totalPrice: Number(row.total_price), currency: row.currency, paymentStatus: row.payment_status })),
        forecasts: forecasts.rows.map(row => ({ forecastId: row.forecast_id, productId: row.product_id, expectedDemand: Number(row.expected_demand), startDate: row.forecast_start_date, endDate: row.forecast_end_date })),
        competitorMappings: mappings.rows.map(row => ({ mappingId: row.mapping_id, productId: row.product_id, isActive: row.is_active }))
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally { client.release(); }
  }

  async close() { await this.pool.end(); }
}

async function setTenantContext(client: PoolClient, tenantId: string, userId: string) {
  await client.query("SELECT set_config('app.current_tenant_id', $1, true), set_config('app.current_user_id', $2, true)", [tenantId, userId]);
}

async function readFacts(client: PoolClient, tenantId: string, periodDays: number): Promise<DashboardDbFacts> {
  const companyResult = await client.query<{ primary_currency: string }>("SELECT primary_currency FROM companies WHERE tenant_id = $1", [tenantId]);
  if (!companyResult.rows[0]) throw new Error("Test tenant is unavailable under the configured tenant context (or RLS denied access).");
  const currency = companyResult.rows[0].primary_currency;
  const ranges = await client.query<{ start_date: Date; end_exclusive: Date; previous_start: Date }>(
    `SELECT (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - ($1::int - 1) * interval '1 day' AS start_date,
            date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' + interval '1 day' AS end_exclusive,
            (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - (2 * $1::int - 1) * interval '1 day' AS previous_start`, [periodDays]);
  const range = ranges.rows[0]!;
  const inv = await client.query<{ paid_invoice_count: string; revenue: string; previous_revenue: string; excluded_currency_count: string }>(
    `SELECT count(*) FILTER (WHERE payment_status = 'PAID' AND currency = $2 AND created_at >= $3 AND created_at < $4) AS paid_invoice_count,
            coalesce(sum(total_amount) FILTER (WHERE payment_status = 'PAID' AND currency = $2 AND created_at >= $3 AND created_at < $4), 0) AS revenue,
            coalesce(sum(total_amount) FILTER (WHERE payment_status = 'PAID' AND currency = $2 AND created_at >= $5 AND created_at < $3), 0) AS previous_revenue,
            count(*) FILTER (WHERE payment_status = 'PAID' AND currency <> $2 AND created_at >= $3 AND created_at < $4) AS excluded_currency_count
       FROM invoices WHERE tenant_id = $1`, [tenantId, currency, range.start_date, range.end_exclusive, range.previous_start]);
  const products = await client.query<{ count: string }>("SELECT count(*) FROM products WHERE tenant_id = $1 AND deleted_at IS NULL", [tenantId]);
  const inventory = await client.query<{ in_stock: string; low_stock: string; out_of_stock: string; total: string }>(
    `SELECT count(*) FILTER (WHERE i.stock_quantity <> 0 AND NOT (i.stock_quantity > 0 AND i.stock_quantity <= i.reorder_level)) AS in_stock,
            count(*) FILTER (WHERE i.stock_quantity > 0 AND i.stock_quantity <= i.reorder_level) AS low_stock,
            count(*) FILTER (WHERE i.stock_quantity = 0) AS out_of_stock,
            count(*) AS total
       FROM inventory i JOIN products p ON p.tenant_id = i.tenant_id AND p.product_id = i.product_id
      WHERE i.tenant_id = $1 AND p.deleted_at IS NULL`, [tenantId]);
  const competitors = await client.query<{ count: string }>("SELECT count(*) FROM tenant_competitors WHERE tenant_id = $1 AND is_tracked = true", [tenantId]);
  const sentiment = await client.query<{ average: string | null; count: string }>(
    `SELECT avg(sr.sentiment_score) AS average, count(*) AS count
       FROM sentiment_results sr JOIN reviews r ON r.tenant_id = sr.tenant_id AND r.review_id = sr.review_id
      WHERE sr.tenant_id = $1 AND r.review_date >= $2 AND r.review_date < $3
        AND r.source_status = 'ALLOWED' AND r.safety_status = 'SAFE'`, [tenantId, range.start_date, range.end_exclusive]);
  const number = (v: string | number | null | undefined) => v == null ? 0 : Number(v);
  return {
    tenantId, currency,
    productCount: number(products.rows[0]?.count),
    paidInvoiceCount: number(inv.rows[0]?.paid_invoice_count),
    revenue: number(inv.rows[0]?.revenue),
    previousRevenue: number(inv.rows[0]?.previous_revenue),
    inventory: { inStock: number(inventory.rows[0]?.in_stock), lowStock: number(inventory.rows[0]?.low_stock), outOfStock: number(inventory.rows[0]?.out_of_stock), total: number(inventory.rows[0]?.total) },
    trackedCompetitors: number(competitors.rows[0]?.count),
    sentimentAverage: sentiment.rows[0]?.average == null ? null : Number(sentiment.rows[0].average),
    qualifyingReviews: number(sentiment.rows[0]?.count),
    invoiceCurrencyExcluded: number(inv.rows[0]?.excluded_currency_count),
    dateRange: { start: range.start_date.toISOString(), endExclusive: range.end_exclusive.toISOString(), previousStart: range.previous_start.toISOString() }
  };
}
