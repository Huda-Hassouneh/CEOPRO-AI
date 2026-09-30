import { prisma } from "../../../config/database.js";
import { getFeatureAccessInfo } from '../../features/repo/usage.repo.js';
import { summarizeForecasts, addDays } from '../../forecasting/service/forecasting.calculations.js';

export const getMainDashboardKPIs = async (
  tenant_id: string,
  periodDays: number = 30
) => {
  // 1. Date Calculations & Setup
  const endDate = new Date();
  const endExclusive = new Date(Date.UTC(endDate.getUTCFullYear(), endDate.getUTCMonth(), endDate.getUTCDate() + 1));
  const startDate = new Date(endExclusive.getTime() - periodDays * 24 * 60 * 60 * 1000);
  const previousPeriodStartDate = new Date(
    startDate.getTime() - periodDays * 24 * 60 * 60 * 1000
  );

  const isoStartDate = startDate.toISOString().split("T")[0];
  const isoEndDate = endDate.toISOString().split("T")[0];

  // 2. Fetch Company Preferences (Currency, Locale)
  const company = await prisma.company.findUnique({
    where: { id: tenant_id },
    select: { primaryCurrency: true, preferredLanguage: true }
  });
  if (!company?.primaryCurrency) throw new Error("Company currency is unavailable");
  const currency = company.primaryCurrency;
  const locale = company?.preferredLanguage || "en";

  // 3. Revenues & Sales Chart Data (Current Period)
  const currentInvoices = await prisma.invoices.findMany({
    where: {
      tenant_id,
      payment_status: "PAID",
      currency,
      created_at: { gte: startDate, lt: endExclusive }
    },
    select: { created_at: true, total_amount: true }
  });

  let currentRevenue = 0;
  const salesPointsMap = new Map<string, number>();

  // Pre-fill dates with 0 for the chart
  for (let i = 0; i < periodDays; i++) {
    const d = new Date(startDate.getTime() + i * 24 * 60 * 60 * 1000);
    salesPointsMap.set(d.toISOString().split("T")[0], 0);
  }

  currentInvoices.forEach((inv) => {
    const amount = Number(inv.total_amount || 0);
    currentRevenue += amount;

    if (inv.created_at) {
      const dateKey = inv.created_at.toISOString().split("T")[0];
      if (salesPointsMap.has(dateKey)) {
        salesPointsMap.set(dateKey, salesPointsMap.get(dateKey)! + amount);
      }
    }
  });

  const salesPoints = Array.from(salesPointsMap.entries())
    .map(([date, value]) => ({ date, value }))
    .sort((a, b) => a.date.localeCompare(b.date));

  // 4. Growth Calculation (Previous Period)
  const previousSales = await prisma.invoices.aggregate({
    _sum: { total_amount: true },
    where: {
      tenant_id,
      payment_status: "PAID",
      currency,
      created_at: { gte: previousPeriodStartDate, lt: startDate }
    }
  });

  const lastRevenue = Number(previousSales._sum.total_amount || 0);
  let growth: number | null = null;
  if (lastRevenue > 0) {
    growth = ((currentRevenue - lastRevenue) / lastRevenue) * 100;
  }

  // 5. Inventory & Products
  const totalProducts = await prisma.products.count({
    where: { tenant_id, deleted_at: null }
  });

  const inventoryData = await prisma.inventory.findMany({
    where: { tenant_id, products: { deleted_at: null } },
    include: { products: { select: { product_name: true } } },
    orderBy: { stock_quantity: "asc" }
  });

  let inStock = 0,
    lowStock = 0,
    outOfStock = 0;

  const inventoryItems = inventoryData.map((inv) => {
    if (inv.stock_quantity === 0) outOfStock++;
    else if (inv.stock_quantity <= inv.reorder_level) lowStock++;
    else inStock++;

    const rawName = inv.products?.product_name as any;
    const productName =
      typeof rawName === "object" && rawName !== null
        ? { en: rawName.en || "Unknown", ar: rawName.ar || "غير معروف" }
        : {
            en: String(rawName || "Unknown"),
            ar: String(rawName || "غير معروف")
          };

    return {
      id: inv.inventory_id,
      product: productName,
      quantity: inv.stock_quantity
    };
  });

  const totalItems = inStock + lowStock + outOfStock;
  const inventoryHealthPercent =
    totalItems > 0 ? Math.round((inStock / totalItems) * 100) : null;

  // 6. Tracked Competitors Count
  const trackedCompetitorsCount = await prisma.tenant_competitors.count({
    where: { tenant_id, is_tracked: true }
  });

  // 7. Market Sentiment
  const sentiment = await prisma.sentiment_results.aggregate({
    _avg: { sentiment_score: true },
    where: {
      tenant_id,
      reviews: {
        review_date: { gte: startDate, lt: endExclusive },
        source_status: "ALLOWED",
        safety_status: "SAFE"
      }
    }
  });

  const sentimentScore = sentiment._avg?.sentiment_score == null ? null : Number(sentiment._avg.sentiment_score);
  const sentimentLabel = sentimentScore == null ? null :
    sentimentScore > 0.1 ? "positive" : sentimentScore < -0.1 ? "negative" : "neutral";

  // 8. Same seven-day demand semantics and boolean entitlement as forecasting.
  const forecastToday = new Date(endExclusive.getTime() - 24 * 60 * 60 * 1000);
  const forecastWindowEnd = addDays(forecastToday, 6);
  const forecastAccess = await getFeatureAccessInfo(tenant_id, 'demand_prediction');
  const rawForecasts = forecastAccess.planFeature ? await prisma.demand_forecasts.findMany({
    where: {
      tenant_id, products: { tenant_id, deleted_at: null },
      OR: [
        { forecast_start_date: { lte: forecastWindowEnd }, forecast_end_date: { gte: forecastToday } },
        { forecast_start_date: null, forecast_end_date: null, forecast_target_date: { gte: forecastToday, lte: forecastWindowEnd } }
      ]
    },
    include: { products: { select: { product_name: true } } },
    orderBy: [{ created_at: { sort: 'desc', nulls: 'last' } }, { forecast_id: 'desc' }]
  }) : [];
  const groupedForecasts = new Map<string, typeof rawForecasts>();
  for (const row of rawForecasts) {
    const group = groupedForecasts.get(row.product_id) ?? [];
    group.push(row);
    groupedForecasts.set(row.product_id, group);
  }
  const demandForecastRows = [...groupedForecasts].sort(([a], [b]) => a.localeCompare(b)).flatMap(([productId, rows]) => {
    const summary = summarizeForecasts(rows, forecastToday, 7, endDate);
    return summary.expectedDemand == null ? [] : [{
      id: productId, product: rows[0]!.products.product_name,
      forecastedDemand: summary.expectedDemand
    }];
  }).slice(0, 4);

  // 9. Fetch Competitor Price Comparison for Dashboard
  const tenantProducts = await prisma.products.findMany({
    where: {
      tenant_id,
      deleted_at: null
    },
    include: {
      // The dashboard formats both prices in the company's currency.
      competitor_product_mappings: {
        where: { is_active: true, tenant_competitors: { is_tracked: true } },
        include: {
          tenant_competitors: {
            include: {
              global_competitors: true
            }
          },
          competitor_prices: {
            where: {
              is_available: true,
              is_exact_data: true,
              source_status: "ALLOWED",
              currency
            },
            orderBy: {
              observed_at: "desc"
            },
            take: 1
          }
        }
      }
    }
  });

  const competitorComparisonRows = tenantProducts
    .map((prod) => {
      const rawName = prod.product_name as any;

      const productName =
        typeof rawName === "object" && rawName !== null
          ? {
              en: rawName.en || "Unknown",
              ar: rawName.ar || "غير معروف"
            }
          : {
              en: String(rawName || "Unknown"),
              ar: String(rawName || "غير معروف")
            };

      if (prod.currency !== currency) return null;
      const ourPrice = Number(prod.current_price);

      const competitorPrices = prod.competitor_product_mappings.flatMap(
        (mapping) =>
          mapping.competitor_prices.map((price) => ({
            price: Number(price.scraped_price),
            competitorName:
              mapping.tenant_competitors?.custom_alias ||
              mapping.tenant_competitors?.global_competitors?.competitor_name ||
              "Unknown Competitor",
            observedAt: price.observed_at
          }))
      );

      if (competitorPrices.length === 0) {
        return null;
      }

      const lowestCompetitor = competitorPrices.reduce((lowest, current) =>
        current.price < lowest.price ? current : lowest
      );

      const lowestCompetitorPrice = lowestCompetitor.price;

      const variance = Number((ourPrice - lowestCompetitorPrice).toFixed(2));

      const direction =
        variance > 0 ? "higher" : variance < 0 ? "lower" : "aligned";

      return {
        id: `comp-row-${prod.product_id}`,
        product: productName,
        competitorName: lowestCompetitor.competitorName,
        ourPrice,
        lowestCompetitorPrice,
        variance,
        direction,
        lastObservedAt: lowestCompetitor.observedAt,
        dataStatus: "verified"
      };
    })
    .filter(Boolean).slice(0, 4);
  // 10. Fetch Recent Activity from Audit Logs
  // 10. Fetch Recent Activity from Audit Logs
  const rawActivities = await prisma.audit_logs.findMany({
    where: { tenant_id },
    orderBy: { created_at: "desc" },
    take: 20
  });

  const recentActivityRows = rawActivities.map((log: any) => {
    // Safely parse the JSON payload whether it's an object or stringified
    let payload: Record<string, any> = {};
    try {
      const parsed = typeof log.changed_data_json === "string"
        ? JSON.parse(log.changed_data_json)
        : log.changed_data_json;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, any>;
    } catch { /* Malformed audit details must not break the dashboard. */ }

    return {
      id: log.audit_id,
      date: log.created_at
        ? new Date(log.created_at).toISOString().split("T")[0]
        : null,
      activity: {
        en: log.action_type || "System Activity",
        ar: log.action_type || "نشاط النظام"
      },
      // If there are no details, pass null so the frontend hides the line completely
      details: typeof payload.details === "string"
        ? { en: payload.details, ar: payload.details }
        : null,
      status: typeof payload.status === "string" ? payload.status.toLowerCase() : null
    };
  });

  // 11. Assemble Frontend-Compliant Payload
  return {
    company: { id: tenant_id, currency, locale },
    availablePeriods: [7, 30, 90],
    period: {
      days: periodDays,
      startDate: isoStartDate,
      endDate: isoEndDate
    },
    metrics: [
      {
        id: "totalSales",
        labelKey: "dashboard.kpis.totalSales",
        value: currentInvoices.length,
        format: "number",
        icon: "sales",
        tone: "blue",
        dataStatus: "verified"
      },
      {
        id: "totalProducts",
        labelKey: "dashboard.kpis.totalProducts",
        value: totalProducts,
        format: "number",
        icon: "products",
        tone: "purple",
        dataStatus: "verified"
      },
      {
        id: "trackedCompetitors",
        labelKey: "dashboard.kpis.trackedCompetitors",
        value: trackedCompetitorsCount,
        format: "number",
        icon: "competitors",
        tone: "teal",
        dataStatus: "verified"
      },
      {
        id: "revenues",
        labelKey: "dashboard.kpis.revenues",
        value: currentRevenue,
        format: "currency",
        icon: "revenue",
        tone: "purple",
        dataStatus: "derived"
      },
      {
        id: "inventoryStatus",
        labelKey: "dashboard.kpis.inventoryStatus",
        value: inventoryHealthPercent,
        format: "percent",
        icon: "inventory",
        tone: "orange",
        dataStatus: inventoryHealthPercent === null ? "unavailable" : "derived"
      },
      {
        id: "marketSentiment",
        labelKey: "dashboard.kpis.marketSentiment",
        value: sentimentLabel,
        format: "sentiment",
        icon: "sentiment",
        tone: "green",
        dataStatus: sentimentLabel === null ? "unavailable" : "estimated"
      },
      {
        id: "growth",
        labelKey: "dashboard.kpis.growth",
        value: growth === null ? null : parseFloat(growth.toFixed(1)),
        format: "signedPercent",
        icon: "growth",
        tone: "green",
        dataStatus: growth === null ? "unavailable" : "derived"
      }
    ],
    salesOverview: {
      dataStatus: "verified",
      currency,
      updatedAt: endDate.toISOString(),
      points: salesPoints
    },
    inventoryStatus: totalItems > 0 ? {
      dataStatus: "verified",
      totals: { inStock, lowStock, outOfStock, totalItems },
      items: inventoryItems
    } : null,
    demandForecast: {
      dataStatus: "estimated",
      source: "forecast-model",
      rows: demandForecastRows
    },
    competitorComparison: {
      dataStatus: "derived",
      currency,
      rows: competitorComparisonRows
    },
    recentActivity: {
      rows: recentActivityRows
    }
  };
};
