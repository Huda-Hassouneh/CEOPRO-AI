export type DashboardDateRange = {
  endDate: Date;
  endExclusive: Date;
  startDate: Date;
  previousPeriodStartDate: Date;
  isoStartDate: string;
  isoEndDate: string;
};

export function createDashboardDateRange(
  periodDays: number,
  now = new Date()
): DashboardDateRange {
  const endExclusive = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1)
  );
  const startDate = new Date(endExclusive.getTime() - periodDays * 86_400_000);
  const previousPeriodStartDate = new Date(
    startDate.getTime() - periodDays * 86_400_000
  );

  return {
    endDate: now,
    endExclusive,
    startDate,
    previousPeriodStartDate,
    isoStartDate: startDate.toISOString().slice(0, 10),
    isoEndDate: now.toISOString().slice(0, 10)
  };
}

export type LocalizedText = { en: string; ar: string };

export function toLocalizedText(value: unknown): LocalizedText {
  if (typeof value === "object" && value !== null) {
    const localized = value as { en?: unknown; ar?: unknown };
    return {
      en: String(localized.en || "Unknown"),
      ar: String(localized.ar || "غير معروف")
    };
  }

  const text = String(value || "Unknown");
  return {
    en: text,
    ar: value ? text : "غير معروف"
  };
}

export type InvoiceForSalesChart = {
  issue_date: Date;
  total_amount: unknown;
};

export function buildSalesOverview(
  invoices: InvoiceForSalesChart[],
  startDate: Date,
  periodDays: number
) {
  const pointsByDate = new Map<string, number>();

  for (let offset = 0; offset < periodDays; offset += 1) {
    const date = new Date(startDate.getTime() + offset * 86_400_000);
    pointsByDate.set(date.toISOString().slice(0, 10), 0);
  }

  let revenue = 0;

  for (const invoice of invoices) {
    const amount = Number(invoice.total_amount || 0);
    revenue += amount;

    const dateKey = invoice.issue_date.toISOString().slice(0, 10);
    const dailyTotal = pointsByDate.get(dateKey);

    if (dailyTotal !== undefined) pointsByDate.set(dateKey, dailyTotal + amount);
  }

  const points = [...pointsByDate.entries()]
    .map(([date, value]) => ({ date, value }))
    .sort((left, right) => left.date.localeCompare(right.date));

  return { revenue, points };
}

export function calculateRevenueGrowth(
  currentRevenue: number,
  previousRevenue: number
): number | null {
  if (previousRevenue <= 0) return null;
  return ((currentRevenue - previousRevenue) / previousRevenue) * 100;
}

type InventoryRecord = {
  inventory_id: string;
  product_id: string;
  stock_quantity: number;
  reorder_level: number;
  products: { product_name: unknown } | null;
};

export function summarizeInventory<T extends InventoryRecord>(records: T[]) {
  let inStock = 0;
  let lowStock = 0;
  let outOfStock = 0;

  const byProduct = new Map<string, { id: string; product: LocalizedText; quantity: number; reorderLevel: number }>();
  for (const record of records) {
    const current = byProduct.get(record.product_id) ?? {
      id: record.product_id,
      product: toLocalizedText(record.products?.product_name),
      quantity: 0,
      reorderLevel: 0
    };
    current.quantity += record.stock_quantity;
    current.reorderLevel += record.reorder_level;
    byProduct.set(record.product_id, current);
  }
  const items = [...byProduct.values()].map(({ id, product, quantity, reorderLevel }) => {
    if (quantity === 0) outOfStock += 1;
    else if (quantity <= reorderLevel) lowStock += 1;
    else inStock += 1;
    return { id, product, quantity };
  }).sort((left, right) => left.quantity - right.quantity);

  const totalItems = inStock + lowStock + outOfStock;
  const healthPercent =
    totalItems > 0 ? Math.round((inStock / totalItems) * 100) : null;

  return { inStock, lowStock, outOfStock, totalItems, healthPercent, items };
}

export function getSentimentLabel(
  score: number | null
): "positive" | "negative" | "neutral" | null {
  if (score === null) return null;
  if (score > 0.1) return "positive";
  if (score < -0.1) return "negative";
  return "neutral";
}

type ForecastRow = { product_id: string };

export function groupForecastsByProduct<T extends ForecastRow>(rows: T[]) {
  const groups = new Map<string, T[]>();

  for (const row of rows) {
    const group = groups.get(row.product_id) ?? [];
    group.push(row);
    groups.set(row.product_id, group);
  }

  return [...groups.entries()].sort(([left], [right]) =>
    left.localeCompare(right)
  );
}

type ForecastWithProductName = {
  product_id: string;
  products: { product_name: unknown };
};

export function buildDemandForecastRows<T extends ForecastWithProductName>(
  rows: T[],
  forecastToday: Date,
  endDate: Date,
  summarize: (
    productForecasts: T[],
    startDate: Date,
    windowDays: number,
    currentDate: Date
  ) => { expectedDemand: number | null }
) {
  return groupForecastsByProduct(rows)
    .flatMap(([productId, productForecasts]) => {
      const summary = summarize(productForecasts, forecastToday, 7, endDate);
      if (summary.expectedDemand == null) return [];

      return [
        {
          id: productId,
          product: productForecasts[0]!.products.product_name,
          forecastedDemand: summary.expectedDemand
        }
      ];
    })
    .slice(0, 4);
}

type CompetitorComparisonProduct = {
  product_id: string;
  product_name: unknown;
  currency: string;
  current_price: unknown;
  competitor_product_mappings: Array<{
    tenant_competitors: {
      custom_alias: string | null;
      global_competitors: { competitor_name: string } | null;
    } | null;
    competitor_prices: Array<{
      scraped_price: unknown;
      observed_at: Date;
    }>;
  }>;
};

export function buildCompetitorComparisonRows(
  products: CompetitorComparisonProduct[],
  currency: string
) {
  return products
    .map((product) => {
      if (product.currency !== currency) return null;

      const prices = product.competitor_product_mappings.flatMap((mapping) =>
        mapping.competitor_prices.map((price) => ({
          price: Number(price.scraped_price),
          competitorName:
            mapping.tenant_competitors?.custom_alias ||
            mapping.tenant_competitors?.global_competitors?.competitor_name ||
            "Unknown Competitor",
          observedAt: price.observed_at
        }))
      );

      if (prices.length === 0) return null;

      const lowestCompetitor = prices.reduce((lowest, current) =>
        current.price < lowest.price ? current : lowest
      );
      const ourPrice = Number(product.current_price);
      const lowestCompetitorPrice = lowestCompetitor.price;
      const variance = Number((ourPrice - lowestCompetitorPrice).toFixed(2));

      return {
        id: `comp-row-${product.product_id}`,
        product: toLocalizedText(product.product_name),
        competitorName: lowestCompetitor.competitorName,
        ourPrice,
        lowestCompetitorPrice,
        variance,
        direction:
          variance > 0 ? ("higher" as const) : variance < 0 ? ("lower" as const) : ("aligned" as const),
        lastObservedAt: lowestCompetitor.observedAt,
        dataStatus: "verified" as const
      };
    })
    .filter((row) => row !== null)
    .slice(0, 4);
}

export function parseAuditPayload(value: unknown): Record<string, unknown> {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value) : value;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // An invalid optional audit payload should not make the dashboard fail.
  }

  return {};
}

export function formatRecentActivity<T extends {
  audit_id: string;
  created_at: Date | null;
  action_type: string | null;
  changed_data_json: unknown;
}>(logs: T[]) {
  return logs.map((log) => {
    const payload = parseAuditPayload(log.changed_data_json);
    const action = log.action_type || "System Activity";

    return {
      id: log.audit_id,
      date: log.created_at ? log.created_at.toISOString().slice(0, 10) : null,
      activity: { en: action, ar: log.action_type || "نشاط النظام" },
      details:
        typeof payload.details === "string"
          ? { en: payload.details, ar: payload.details }
          : null,
      status:
        typeof payload.status === "string" ? payload.status.toLowerCase() : null
    };
  });
}

