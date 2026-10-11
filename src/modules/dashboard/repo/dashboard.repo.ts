import { prisma } from "../../../config/database.js";
import { getFeatureAccessInfo } from "../../features/repo/usage.repo.js";
import {
  addDays,
  summarizeForecasts
} from "../../forecasting/service/forecasting.calculations.js";
import {
  buildCompetitorComparisonRows,
  buildDemandForecastRows,
  buildSalesOverview,
  calculateRevenueGrowth,
  createDashboardDateRange,
  formatRecentActivity,
  getSentimentLabel,
  summarizeInventory
} from "../helper/dashboard.helpers.js";

export const getMainDashboardKPIs = async (
  tenant_id: string,
  user_id: string,
  periodDays: number = 30
) =>
  prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${tenant_id}, true),
        set_config('app.current_user_id', ${user_id}, true)
    `;

    const dateRange = createDashboardDateRange(periodDays);

    const company = await tx.company.findUnique({
      where: { id: tenant_id },
      select: { primaryCurrency: true, preferredLanguage: true }
    });

    if (!company?.primaryCurrency) {
      throw new Error("Company currency is unavailable");
    }

    const currency = company.primaryCurrency;
    const locale = company.preferredLanguage || "en";

    const currentInvoices = await tx.invoices.findMany({
      where: {
        tenant_id,
        payment_status: "PAID",
        currency,
        created_at: {
          gte: dateRange.startDate,
          lt: dateRange.endExclusive
        }
      },
      select: { created_at: true, total_amount: true }
    });
    const salesOverview = buildSalesOverview(
      currentInvoices,
      dateRange.startDate,
      periodDays
    );

    const previousSales = await tx.invoices.aggregate({
      _sum: { total_amount: true },
      where: {
        tenant_id,
        payment_status: "PAID",
        currency,
        created_at: {
          gte: dateRange.previousPeriodStartDate,
          lt: dateRange.startDate
        }
      }
    });
    const previousRevenue = Number(previousSales._sum.total_amount || 0);
    const growth = calculateRevenueGrowth(
      salesOverview.revenue,
      previousRevenue
    );

    const totalProducts = await tx.products.count({
      where: { tenant_id, deleted_at: null }
    });
    const inventoryData = await tx.inventory.findMany({
      where: { tenant_id, products: { deleted_at: null } },
      select: {
        inventory_id: true,
        stock_quantity: true,
        reorder_level: true,
        products: { select: { product_name: true } }
      },
      orderBy: { stock_quantity: "asc" }
    });
    const inventory = summarizeInventory(inventoryData);

    const trackedCompetitorsCount = await tx.tenant_competitors.count({
      where: { tenant_id, is_tracked: true }
    });

    const sentimentAggregate = await tx.sentiment_results.aggregate({
      _avg: { sentiment_score: true },
      where: {
        tenant_id,
        reviews: {
          review_date: {
            gte: dateRange.startDate,
            lt: dateRange.endExclusive
          },
          source_status: "ALLOWED",
          safety_status: "SAFE"
        }
      }
    });
    const sentimentScore =
      sentimentAggregate._avg?.sentiment_score == null
        ? null
        : Number(sentimentAggregate._avg.sentiment_score);
    const sentimentLabel = getSentimentLabel(sentimentScore);

    const forecastToday = new Date(
      dateRange.endExclusive.getTime() - 86_400_000
    );
    const forecastWindowEnd = addDays(forecastToday, 6);
    const forecastAccess = await getFeatureAccessInfo(
      tenant_id,
      "demand_prediction",
      tx
    );
    const rawForecasts = forecastAccess.planFeature
      ? await tx.demand_forecasts.findMany({
          where: {
            tenant_id,
            products: { tenant_id, deleted_at: null },
            OR: [
              {
                forecast_start_date: { lte: forecastWindowEnd },
                forecast_end_date: { gte: forecastToday }
              },
              {
                forecast_start_date: null,
                forecast_end_date: null,
                forecast_target_date: {
                  gte: forecastToday,
                  lte: forecastWindowEnd
                }
              }
            ]
          },
          include: { products: { select: { product_name: true } } },
          orderBy: [
            { created_at: { sort: "desc", nulls: "last" } },
            { forecast_id: "desc" }
          ]
        })
      : [];

    const demandForecastRows = buildDemandForecastRows(
      rawForecasts,
      forecastToday,
      dateRange.endDate,
      summarizeForecasts
    );

    const tenantProducts = await tx.products.findMany({
      where: { tenant_id, deleted_at: null },
      select: {
        product_id: true,
        product_name: true,
        currency: true,
        current_price: true,
        competitor_product_mappings: {
          where: {
            is_active: true,
            tenant_competitors: { is_tracked: true }
          },
          select: {
            tenant_competitors: {
              select: {
                custom_alias: true,
                global_competitors: {
                  select: { competitor_name: true }
                }
              }
            },
            competitor_prices: {
              where: {
                is_available: true,
                is_exact_data: true,
                source_status: "ALLOWED",
                currency
              },
              select: { scraped_price: true, observed_at: true },
              orderBy: { observed_at: "desc" },
              take: 1
            }
          }
        }
      }
    });
    const competitorComparisonRows = buildCompetitorComparisonRows(
      tenantProducts,
      currency
    );

    const rawActivities = await tx.audit_logs.findMany({
      where: { tenant_id },
      orderBy: { created_at: "desc" },
      take: 20,
      select: {
        audit_id: true,
        created_at: true,
        action_type: true,
        changed_data_json: true
      }
    });
    const recentActivityRows = formatRecentActivity(rawActivities);

    return {
      company: { id: tenant_id, currency, locale },
      availablePeriods: [7, 30, 90],
      period: {
        days: periodDays,
        startDate: dateRange.isoStartDate,
        endDate: dateRange.isoEndDate
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
          value: salesOverview.revenue,
          format: "currency",
          icon: "revenue",
          tone: "purple",
          dataStatus: "derived"
        },
        {
          id: "inventoryStatus",
          labelKey: "dashboard.kpis.inventoryStatus",
          value: inventory.healthPercent,
          format: "percent",
          icon: "inventory",
          tone: "orange",
          dataStatus:
            inventory.healthPercent === null ? "unavailable" : "derived"
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
          value: growth === null ? null : Number(growth.toFixed(1)),
          format: "signedPercent",
          icon: "growth",
          tone: "green",
          dataStatus: growth === null ? "unavailable" : "derived"
        }
      ],
      salesOverview: {
        dataStatus: "verified",
        currency,
        updatedAt: dateRange.endDate.toISOString(),
        points: salesOverview.points
      },
      inventoryStatus:
        inventory.totalItems > 0
          ? {
              dataStatus: "verified",
              totals: {
                inStock: inventory.inStock,
                lowStock: inventory.lowStock,
                outOfStock: inventory.outOfStock,
                totalItems: inventory.totalItems
              },
              items: inventory.items
            }
          : null,
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
      recentActivity: { rows: recentActivityRows }
    };
  });
