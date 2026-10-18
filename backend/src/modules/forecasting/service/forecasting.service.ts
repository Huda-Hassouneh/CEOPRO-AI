import { Prisma } from "../../../generated/prisma/client.js";
import { createAiIntegrationError } from "../../../integrations/ai/ai.types.js";
import { getFeatureAccessInfo } from "../../features/repo/usage.repo.js";
import { ForecastAccessError, historyIsUsable, inventoryContext, sourceFreshness, usableForecasts } from "./forecasting.policy.js";
import { supportedInventoryRecommendation } from "./inventory-recommendation.js";
import { requestDemandForecast } from "../client/forecasting.client.js";
import {
  loadForecastData,
  loadForecastGenerationInput,
  persistGeneratedForecast
} from "../repo/forecasting.repo.js";
import {
  addDays,
  dayKey,
  finiteNumber,
  forecastWindow,
  forecastWindowDays,
  interval,
  latestForecasts,
  summarizeForecasts,
  utcDay
} from "./forecasting.calculations.js";
type Snapshot = Awaited<ReturnType<typeof loadForecastData>>;
type StoredForecast = Snapshot["forecasts"][number];
type StoredModelVersion = Snapshot["modelVersions"][number];

function parseUtcDate(dateText: string): Date {
  const date = new Date(`${dateText}T00:00:00.000Z`);
  if (
    Number.isNaN(date.getTime()) ||
    date.toISOString().slice(0, 10) !== dateText
  ) {
    throw createAiIntegrationError(
      "Gradio forecasting returned an invalid target date.",
      "malformed_response"
    );
  }
  return date;
}

function toInputJson(value: unknown): Prisma.InputJsonValue {
  const serialized = JSON.stringify(value);
  if (serialized === undefined) return {};
  const parsed: unknown = JSON.parse(serialized);
  return parsed === null ? {} : (parsed as Prisma.InputJsonValue);
}

const pendingGeneration = new Map<string, Promise<Awaited<ReturnType<typeof generateOnce>>>>();
async function requireDemandAccess(tenantId: string) {
  const { subscription, planFeature } = await getFeatureAccessInfo(tenantId, "demand_prediction");
  if (!subscription) throw new ForecastAccessError("SUBSCRIPTION_NOT_FOUND");
  if (!planFeature) throw new ForecastAccessError("FEATURE_NOT_INCLUDED");
}
async function inventoryAccess(tenantId: string) {
  const { subscription, planFeature } = await getFeatureAccessInfo(tenantId, "inventory_intelligence");
  return Boolean(subscription && planFeature);
}
export async function generateDemandForecast(input: {
  tenantId: string; userId: string; productId: string; horizonDays: number;
}) {
  await requireDemandAccess(input.tenantId);
  if (!Number.isInteger(input.horizonDays) || input.horizonDays < 1 || input.horizonDays > 60) {
    throw createAiIntegrationError("Forecast horizon must be between 1 and 60 days.", "configuration");
  }
  const key = JSON.stringify([input.tenantId, input.userId, input.productId, input.horizonDays]);
  const existing = pendingGeneration.get(key);
  if (existing) return existing;
  const pending = generateOnce(input);
  pendingGeneration.set(key, pending);
  try { return await pending; }
  finally { if (pendingGeneration.get(key) === pending) pendingGeneration.delete(key); }
}
async function generateOnce(input: { tenantId: string; userId: string; productId: string; horizonDays: number }) {
  const product = await loadForecastGenerationInput(input);
  if (!product) return null;
  const asOf = new Date();
  const dates = product.transactions.map((row) => row.transaction_date).sort();
  const latestHistoryDate = dates.at(-1) ?? null;
  const salesFreshness = sourceFreshness(latestHistoryDate ? new Date(`${latestHistoryDate}T00:00:00Z`) : null, utcDay(asOf));
  const context = {
    product_id: product.productId, product_name: product.productName, horizon_days: input.horizonDays,
    prediction_kind: "target_day" as const, checked_at: asOf.toISOString(),
    latest_history_date: latestHistoryDate, sales_freshness: salesFreshness,
    price_currency: product.priceCurrency,
    history_days_supplied: product.transactions.length
  };
  const unavailable = (reason: string, analysisPerformed = false, dataSufficiency: unknown = null) => ({
    ...context, status: "UNKNOWN" as const, reason, analysis_performed: analysisPerformed,
    source: null, expected_demand: null, forecast_target_date: null, forecast_start_date: null,
    confidence_score: null, confidence_range: { lower: null, upper: null }, model_version: null,
    data_sufficiency: dataSufficiency, transactions_used: 0, forecast_id: null, evidence_id: null
  });
  if (!product.transactions.length) return unavailable("NO_HISTORY");
  if (!historyIsUsable(product.transactions, asOf) || product.invalidRecords > 0) return unavailable("INVALID_HISTORY");
  if (!product.productName) return unavailable("PRODUCT_METADATA_UNAVAILABLE");
  const expectedTarget = addDays(utcDay(asOf), input.horizonDays);
  const modelHorizonDays = Math.round((expectedTarget.getTime() - parseUtcDate(latestHistoryDate!).getTime()) / 86_400_000);
  // The provider counts steps from the final observation. The UI counts its
  // selected future days from today. Account for the gap without invented sales.
  if (modelHorizonDays > 60 || salesFreshness.status === "stale") return unavailable("STALE_HISTORY");
  const response = await requestDemandForecast({
    transactions: product.transactions.map((row) => ({ ...row, product_name: product.productName! })),
    horizonDays: modelHorizonDays, currentPrice: product.currentPrice,
    currentStock: product.currentStock, currency: product.priceCurrency, productName: product.productName
  });
  if (response.result.status === "UNKNOWN") return {
    ...unavailable("MODEL_UNAVAILABLE", true, response.result.data_sufficiency),
    transactions_used: response.transactions_used, model_horizon_days: modelHorizonDays
  };
  const result = response.result;
  const targetDate = parseUtcDate(result.forecast_target_date);
  if (targetDate.getTime() !== expectedTarget.getTime()) {
    throw createAiIntegrationError("Forecast target does not match the supplied history and horizon.", "malformed_response");
  }
  await requireDemandAccess(input.tenantId);
  const expectedDemand = result.expected_demand;
  const saved = await persistGeneratedForecast({
    tenantId: input.tenantId, userId: input.userId, productId: product.productId,
    forecastStartDate: targetDate, forecastEndDate: targetDate, forecastTargetDate: targetDate,
    expectedDemand, rawExpectedDemand: result.expected_demand, source: result.source,
    confidenceScore: result.confidence_score ?? null,
    lowerBound: result.confidence_range_lower ?? null, upperBound: result.confidence_range_upper ?? null,
    modelVersion: result.model_version ?? null, modelName: result.model_name ?? null,
    transactionsUsed: response.transactions_used, horizonDays: input.horizonDays,
    modelHorizonDays, priceCurrency: product.priceCurrency,
    dataSufficiency: toInputJson(result.data_sufficiency), latestHistoryDate,
    historyDaysSupplied: product.transactions.length
  });
  if (!saved) return null;
  return {
    ...context, status: "OK" as const, reason: null, analysis_performed: true,
    generated_at: new Date().toISOString(),
    model_horizon_days: modelHorizonDays,
    source: result.source, expected_demand: expectedDemand, raw_expected_demand: result.expected_demand,
    forecast_target_date: result.forecast_target_date, forecast_start_date: result.forecast_target_date,
    confidence_score: result.confidence_score ?? null,
    confidence_range: { lower: result.confidence_range_lower ?? null, upper: result.confidence_range_upper ?? null },
    model_version: result.model_version ?? null, data_sufficiency: result.data_sufficiency,
    transactions_used: response.transactions_used, forecast_id: saved.forecastId, evidence_id: saved.evidenceId
  };
}

type ModelPerformance = {
  modelVersionId: string;
  modelName: string;
  version: string;
  status: string;
  trainedAt: string | null;
  mae: number | null;
  rmse: number | null;
  mase: number | null;
  nFolds: number | null;
  baselineScores: Record<string, unknown> | null;
};
const groupByProduct = <T extends { product_id: string }>(rows: T[]) => {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const group = groups.get(row.product_id) ?? [];
    group.push(row);
    groups.set(row.product_id, group);
  }
  return groups;
};
const jsonObject = (value: unknown): Record<string, unknown> | null => {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

const nonnegativeMetric = (value: unknown) => { const number = typeof value === "number" ? finiteNumber(value) : null; return number !== null && number >= 0 ? number : null; };
function reportedVersion(row: StoredForecast) {
  const metadata = jsonObject(row.features_used);
  const legacySourceLabel = metadata && metadata.prediction_kind === undefined &&
    typeof metadata.horizon_days === "number" && "transactions_used" in metadata &&
    "data_sufficiency" in metadata && row.model_version === metadata.source;
  return row.model_version === "UNSPECIFIED" || legacySourceLabel ? null : row.model_version;
}
const resolveModelPerformance = (
  rows: StoredForecast[],
  modelVersions: StoredModelVersion[]
): ModelPerformance | null => {
  const versions = [
    ...new Set(
      rows
        .map((row) => reportedVersion(row)?.trim())
        .filter(
          (version): version is string =>
            typeof version === "string" && version.length > 0 && version !== "UNSPECIFIED"
        )
    )
  ];

  // One requested horizon must resolve to one model version. Do not combine
  // evaluation metrics from different model versions.
  if (versions.length !== 1) return null;

  const matches = modelVersions.filter(
    (modelVersion) => modelVersion.version === versions[0]
  );

  // model_versions.version is not currently guaranteed unique by the schema.
  // Refuse to guess when the registry contains an ambiguous match.
  if (matches.length !== 1) return null;

  const modelVersion = matches[0];
  const metrics = jsonObject(modelVersion.metrics);
  if (!metrics) return null;

  const nFoldsValue = typeof metrics.n_folds === "number" ? finiteNumber(metrics.n_folds) : null;

  return {
    modelVersionId: modelVersion.model_version_id,
    modelName: modelVersion.model_name,
    version: modelVersion.version,
    status: modelVersion.status,
    trainedAt: modelVersion.trained_at?.toISOString() ?? null,
    mae: nonnegativeMetric(metrics.mae),
    rmse: nonnegativeMetric(metrics.rmse),
    mase: nonnegativeMetric(metrics.mase),
    nFolds:
      nFoldsValue != null && Number.isInteger(nFoldsValue) && nFoldsValue >= 0
        ? nFoldsValue
        : null,
    baselineScores: jsonObject(metrics.baseline_scores)
  };
};

const serialize = (forecast: StoredForecast) => {
  const window = forecastWindow(forecast);
  if (!window) return null;
  const bounds = interval(forecast);
  return {
    id: forecast.forecast_id,
    date: dayKey(window.start),
    endDate: dayKey(window.end),
    forecastedDemand: forecast.expected_demand,
    lowerBound: bounds.lower,
    upperBound: bounds.upper,
    actualDemand: null as number | null,
    dataStatus: "estimated",
    modelVersion: reportedVersion(forecast),
    predictionKind: forecastWindowDays(forecast) === 1 ? "target_day" : "period_total",
    confidenceScore: nonnegativeMetric(jsonObject(forecast.features_used)?.confidence_score),
    source: jsonObject(forecast.features_used)?.source ?? null,
    generatedAt: forecast.created_at?.toISOString() ?? null
  };
};
function productSummary(
  product: Snapshot["products"][number],
  inventory: Snapshot["inventory"],
  forecasts: StoredForecast[],
  start: Date,
  days: number,
  now: Date,
  includeRecommendations = false
) {
  const end = addDays(start, days - 1);
  const relevantForecasts = forecasts.filter((row) => {
    const window = forecastWindow(row);
    return window && window.start <= end && window.end >= start;
  });
  const validForecasts = usableForecasts(forecasts, now);
  const summary = summarizeForecasts(validForecasts, start, days, now);
  const timingRows = summary.status === "complete" ? summary.summaryRows : relevantForecasts;
  const stockContext = inventoryContext(inventory, now);
  const { currentStock, safetyStock, freshness: stockFreshness } = stockContext;
  /*
   * Summary metrics and recommendations must use only the rows selected by the
   * calculations layer for this exact requested horizon.
   *
   * When the requested horizon is represented by multiple daily rows, there is
   * no single horizon-level recommendation whose suggested quantity can safely
   * be treated as the recommendation for the entire period. In that case keep
   * the recommendation unavailable instead of borrowing one daily result.
   */
  const recommendationRows =
    includeRecommendations && summary.status === "complete" && summary.summaryRows.length === 1
      ? summary.summaryRows
      : [];
  const recResult = includeRecommendations
    ? supportedInventoryRecommendation(recommendationRows as StoredForecast[], stockContext, summary.status, summary.expectedDemand, now)
    : null;
  const rec = recResult?.recommendation ?? null;
  const targetDate =
    summary.status === "complete" && summary.summaryRows.length
      ? dayKey(
          new Date(
            Math.max(
              ...summary.summaryRows.map((forecast) =>
                forecastWindow(forecast)!.end.getTime()
              )
            )
          )
        )
      : null;
  /*
   * Keep daily rows available for charts independently from the horizon row
   * used by the summary cards. Multi-day rows are not daily chart points.
   */
  const dailyForecasts = summary.selected
    .filter((forecast) => forecastWindowDays(forecast) === 1)
    .map(serialize)
    .filter(
      (forecast): forecast is NonNullable<typeof forecast> => forecast != null
    );
  return {
    id: product.product_id,
    name: product.product_name,
    category: product.category,
    currentStock,
    safetyStock,
    expectedDemand: summary.expectedDemand,
    targetDate,
    trend: summary.trend,
    confidenceRange: summary.confidenceRange,
    recommendedAction: rec?.action ?? null,
    suggestedQuantity: rec?.suggestedQuantity ?? null,
    priority: null,
    modelAccuracy: null,
    dataStatus: summary.expectedDemand != null ? "estimated" : null,
    stockDataStatus: currentStock !== null ? "derived" : stockFreshness.status === "stale" ? "stale" : null,
    stockFreshness,
    forecastGeneratedAt: timingRows.some((row) => row.created_at && row.created_at <= now) ? new Date(Math.max(...timingRows.filter((row) => row.created_at && row.created_at <= now).map((row) => row.created_at!.getTime()))).toISOString() : null,
    latestPrediction: latestForecasts(validForecasts, now).filter((row) => forecastWindow(row)!.start >= start && forecastWindow(row)!.end <= end)
      .sort((a, b) => (b.created_at?.getTime() ?? 0) - (a.created_at?.getTime() ?? 0) || forecastWindow(b)!.end.getTime() - forecastWindow(a)!.end.getTime()).map(serialize)[0] ?? null,
    coverage: {
      status: summary.status === "unavailable" && relevantForecasts.some((row) => sourceFreshness(row.created_at, now).status === "stale") ? "stale" : summary.status,
      coveredDays: summary.coveredDays,
      periodDays: days
    },
    forecast: dailyForecasts,
    recommendation: rec,
    recommendationStatus: recResult?.status ?? null,
    stockEvidence: { warehouseCount: stockContext.warehouseCount, latestUpdatedAt: stockContext.latestUpdatedAt, oldestUpdatedAt: stockFreshness.timestamp, reason: stockContext.reason }
  };
}
export const getDemandOverview = async (
  tenantId: string,
  periodDays: number,
  productId: string,
  userId: string
) => {
  const now = new Date();
  const start = addDays(utcDay(now), 1);
  const end = addDays(start, periodDays - 1);
  // Load one preceding horizon as well as the requested horizon. Interval-based
  // forecasts need the preceding comparable period to derive increase/decrease/
  // stable without inventing daily values from an aggregate forecast.
  const comparisonStart = addDays(start, -periodDays);
  const canRecommend = await inventoryAccess(tenantId);
  const snapshot = await loadForecastData(
    tenantId,
    userId,
    comparisonStart,
    end,
    productId
  );
  if (
    productId !== "all" &&
    !snapshot.products.some((product) => product.product_id === productId)
  ) {
    return null;
  }
  const stocks = groupByProduct(snapshot.inventory);
  const forecasts = groupByProduct(snapshot.forecasts);
  const selected = snapshot.products.filter(
    (product) => productId === "all" || product.product_id === productId
  );
  const rows = selected.map((product) =>
    productSummary(
      product,
      stocks.get(product.product_id) ?? [],
      forecasts.get(product.product_id) ?? [],
      start,
      periodDays,
      now,
      canRecommend
    )
  );
  const completeRows = rows.filter(
    (product) =>
      product.coverage.status === "complete" && product.expectedDemand != null
  );
  // Do not blank the tenant-wide forecast merely because one catalog product
  // has no forecast. Sum only products with a complete requested horizon; the
  // productsForecasted metric exposes exactly how many products contributed.
  const total = completeRows.length
    ? completeRows.reduce((sum, product) => sum + product.expectedDemand!, 0)
    : null;
  const points = Array.from({ length: periodDays }, (_, index) => {
    const date = dayKey(addDays(start, index));
    const values = rows.map(
      (product) =>
        product.forecast.find(
          (forecast) => forecast.date === date && forecast.endDate === date
        )?.forecastedDemand ?? null
    );
    const coveredProducts = values.filter((value) => value != null).length;
    // Multi-day horizon forecasts are aggregate totals and must never be smeared
    // across chart days. A chart point exists only when every selected product
    // has an actual daily forecast for that date.
    return {
      date,
      value:
        rows.length > 0 && coveredProducts === rows.length
          ? values.reduce<number>((sum, value) => sum + value!, 0)
          : null,
      coveredProducts,
      totalProducts: rows.length
    };
  });
  const modelEvaluations = rows.flatMap((product) => {
    const candidates = latestForecasts(usableForecasts(forecasts.get(product.id) ?? [], now), now)
      .filter((row) => { const window = forecastWindow(row)!; return window.start >= start && window.end <= end; });
    const versions = [...new Set(candidates.map(reportedVersion).filter((version): version is string => Boolean(version)))];
    return versions.flatMap((version) => {
      const performance = resolveModelPerformance(candidates.filter((row) => reportedVersion(row) === version), snapshot.modelVersions);
      return performance && [performance.mae, performance.rmse, performance.mase].some((value) => value !== null)
        ? [{ productId: product.id, productName: product.name, ...performance }] : [];
    });
  });
  const hasTrend = rows.some((product) => product.trend != null);
  return {
    companyId: tenantId,
    featureAccess: { inventoryIntelligence: canRecommend },
    generatedAt: now.toISOString(),
    filters: {
      productId,
      periodDays,
      startDate: dayKey(start),
      endDate: dayKey(end),
      timeZone: "UTC"
    },
    modelEvaluations,
    sectionStatuses: { forecasts: rows.length && completeRows.length === rows.length ? "estimated" : rows.some((row) => row.coverage.coveredDays > 0) ? "partial" : rows.some((row) => row.coverage.status === "stale") ? "stale" : "unavailable" },
    availablePeriods: [7, 30],
    products: snapshot.products.map((product) => ({
      id: product.product_id,
      name: product.product_name,
      category: product.category
    })),
    metrics: [
      {
        id: "next30Forecast",
        value: total,
        dataStatus: total == null ? null : completeRows.length === rows.length ? "estimated" : "partial",
        icon: "calendar"
      },
      {
        id: "productsForecasted",
        value: completeRows.length,
        dataStatus: "derived",
        icon: "package"
      },
      ...(["increasing", "decreasing", "stable"] as const).map(
        (trend, index) => ({
          id: ["predictedIncrease", "predictedDecrease", "stableDemand"][index],
          value: hasTrend
            ? rows.filter((product) => product.trend === trend).length
            : null,
          dataStatus: hasTrend ? "derived" : null,
          icon: ["increase", "decrease", "stable"][index]
        })
      )
    ],
    totalForecast: {
      points,
      dataStatus: points.some((point) => point.value != null)
        ? points.every((point) => point.value != null) ? "estimated" : "partial"
        : null
    },
    forecasts: rows.map(
      ({ forecast, recommendation: _recommendation, ...product }) => product
    )
  };
};
export const getDemandDetail = async (
  tenantId: string,
  productId: string,
  userId: string,
  periodDays = 30
) => {
  const now = new Date();
  const start = addDays(utcDay(now), 1);
  const end = addDays(start, periodDays - 1);
  const historyStart = addDays(start, -30);
  const canRecommend = await inventoryAccess(tenantId);
  const snapshot = await loadForecastData(
    tenantId,
    userId,
    historyStart,
    addDays(end, 1),
    productId,
    true
  );
  const product = snapshot.products.find(
    (candidate) => candidate.product_id === productId
  );
  if (!product) return null;
  const summary = productSummary(
    product,
    snapshot.inventory,
    snapshot.forecasts,
    start,
    periodDays,
    now,
    canRecommend
  );
  const historical = latestForecasts(
    snapshot.forecasts.filter((forecast) => {
      const window = forecastWindow(forecast);
      // Evaluate only predictions made before the measured period, never
      // hindsight revisions.
      return (
        window != null &&
        window.start >= historyStart &&
        window.end < start &&
        forecast.created_at != null &&
        forecast.created_at < window.start
      );
    }),
    now
  );
  const future = latestForecasts(usableForecasts(snapshot.forecasts, now), now).filter((forecast) => {
    const window = forecastWindow(forecast);
    return window != null && window.start <= end && window.end >= start;
  });
  const historyRows = [...historical, ...future]
    .map(serialize)
    .filter(
      (forecast): forecast is NonNullable<typeof forecast> => forecast != null
    );
  const actuals = new Map(
    snapshot.history
      .filter((row) => row.date < dayKey(start))
      .map((row) => [row.date, Number(row.units)])
  );
  // These are recorded units only: absent transaction dates are unknown, not
  // zero sales.
  for (const row of historyRows) {
    if (row.endDate >= dayKey(start)) continue;
    const observations = [...actuals].filter(
      ([date]) => date >= row.date && date <= row.endDate
    );
    row.actualDemand = observations.length
      ? observations.reduce((sum, [, units]) => sum + units, 0)
      : null;
  }
  /*
   * Chart only true daily forecasts. A 7-day/30-day aggregate forecast may
   * overlap those dates, but that is expected and must not hide the daily series.
   */
  const dailyForecasts = new Map(
    historyRows
      .filter((forecast) => forecast.date === forecast.endDate)
      .map((forecast) => [forecast.date, forecast])
  );
  const points = Array.from({ length: 30 + periodDays }, (_, index) => {
    const date = dayKey(addDays(historyStart, index));
    const row = dailyForecasts.get(date);
    return {
      date,
      actual: actuals.get(date) ?? null,
      forecast: row?.forecastedDemand ?? null,
      lower: row?.lowerBound ?? null,
      upper: row?.upperBound ?? null
    };
  });
  const hasForecastChartData = points.some((point) => point.forecast != null);
  const detailForecastSummary = summarizeForecasts(
    usableForecasts(snapshot.forecasts, now),
    start,
    periodDays,
    now
  );
  const modelPerformance = resolveModelPerformance(
    detailForecastSummary.summaryRows as StoredForecast[],
    snapshot.modelVersions
  );
  return {
    companyId: tenantId,
    featureAccess: { inventoryIntelligence: canRecommend },
    generatedAt: now.toISOString(),
    filters: {
      productId,
      periodDays,
      startDate: dayKey(start),
      endDate: dayKey(end),
      timeZone: "UTC"
    },
    product: {
      id: summary.id,
      name: summary.name,
      category: summary.category
    },
    coverage: summary.coverage,
    forecastGeneratedAt: summary.forecastGeneratedAt,
    latestPrediction: summary.latestPrediction,
    stockFreshness: summary.stockFreshness,
    metrics: [
      {
        id: "currentStock",
        value: summary.currentStock,
        dataStatus: summary.stockDataStatus,
        format: "units"
      },
      {
        id: "expectedDemand",
        value: summary.expectedDemand,
        dataStatus: summary.dataStatus,
        format: "units"
      },
      {
        id: "targetDate",
        value: summary.targetDate,
        dataStatus: summary.dataStatus,
        format: "date"
      },
      {
        id: "confidenceRange",
        value: summary.confidenceRange,
        dataStatus: summary.confidenceRange.lower !== null && summary.confidenceRange.upper !== null ? summary.dataStatus : null,
        format: "range"
      },
      {
        id: "modelPerformance",
        value: modelPerformance?.mase ?? null,
        dataStatus: modelPerformance?.mase != null ? "estimated" : null,
        format: "decimal",
        metric: "MASE",
        lowerIsBetter: true
      }
    ],
    chart: {
      points,
      dataStatus: hasForecastChartData ? "estimated" : null
    },
    forecastHistory: historyRows,
    recommendation: summary.recommendation,
    recommendationStatus: summary.recommendationStatus,
    stockEvidence: summary.stockEvidence,
    aiInsight: null,
    modelPerformance,
    pipelineStatus: "unavailable"
  };
};
