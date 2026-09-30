import { loadForecastData } from "../repo/forecasting.repo.js";
import {
  addDays,
  dayKey,
  forecastWindow,
  finiteNumber,
  interval,
  latestForecasts,
  summarizeForecasts,
  utcDay
} from "./forecasting.calculations.js";

type Snapshot = Awaited<ReturnType<typeof loadForecastData>>;
type StoredForecast = Snapshot["forecasts"][number];

const groupByProduct = <T extends { product_id: string }>(rows: T[]) => {
  const groups = new Map<string, T[]>();

  for (const row of rows) {
    const group = groups.get(row.product_id) ?? [];
    group.push(row);
    groups.set(row.product_id, group);
  }

  return groups;
};

const recommendation = (
  rows: StoredForecast[],
  stock: number | null,
  safety: number | null
) => {
  const candidates = rows.flatMap((forecast) =>
    forecast.recommendation_outcomes.map((result) => ({ forecast, result }))
  );

  candidates.sort(
    (a, b) =>
      (b.result.created_at?.getTime() ?? 0) -
        (a.result.created_at?.getTime() ?? 0) ||
      b.result.recommendation_id.localeCompare(a.result.recommendation_id)
  );

  const candidate = candidates[0];
  if (!candidate) return null;

  const { forecast, result } = candidate;

  // Do not invent action thresholds or interpret arbitrary JSON as ML output.
  const action = result.recommended_action?.trim().toLowerCase();
  if (!action || !["restock", "reduce", "monitor"].includes(action)) return null;

  const window = forecastWindow(forecast)!;

  return {
    id: result.recommendation_id,
    action,
    suggestedQuantity:
      action === "restock" && stock != null && safety != null
        ? Math.max(0, forecast.expected_demand + safety - stock)
        : null,
    priority: null,
    targetDate: dayKey(window.end),
    startDate: dayKey(window.start),
    modelAccuracy: null,
    dataStatus: "estimated",
    quantityDataStatus: "derived",
    generatedAt: result.created_at?.toISOString() ?? null
  };
};

const serialize = (forecast: StoredForecast) => {
  const window = forecastWindow(forecast)!;
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
    modelVersion: forecast.model_version,
    generatedAt: forecast.created_at?.toISOString() ?? null
  };
};

function productSummary(
  product: Snapshot["products"][number],
  inventory: Snapshot["inventory"],
  forecasts: StoredForecast[],
  start: Date,
  days: number,
  now: Date
) {
  const summary = summarizeForecasts(forecasts, start, days, now);

  // Inventory rows are warehouse positions, so stock is additive across rows.
  const currentStock = inventory.length
    ? inventory.reduce((sum, row) => sum + row.stock_quantity, 0)
    : null;

  // Missing safety stock is unknown, not zero. Only expose an aggregate when
  // every contributing inventory row has a finite safety-stock value.
  const safetyValues = inventory.map((row) => finiteNumber(row.safety_stock));
  const hasCompleteSafetyStock =
    safetyValues.length > 0 && safetyValues.every((value) => value != null);
  const safetyStock = hasCompleteSafetyStock
    ? safetyValues.reduce<number>((sum, value) => sum + value!, 0)
    : null;

  const rec = recommendation(
    summary.status === "overlapping"
      ? []
      : summary.selected.filter((forecast) => {
          const window = forecastWindow(forecast)!;
          return (
            window.start >= start &&
            window.end <= addDays(start, days - 1)
          );
        }),
    currentStock,
    safetyStock
  );

  return {
    id: product.product_id,
    name: product.product_name,
    category: product.category,
    currentStock,
    safetyStock,
    expectedDemand: summary.expectedDemand,
    targetDate: summary.selected.length
      ? dayKey(
          new Date(
            Math.max(
              ...summary.selected.map(
                (forecast) => forecastWindow(forecast)!.end.getTime()
              )
            )
          )
        )
      : null,
    trend: summary.trend,
    confidenceRange: summary.confidenceRange,
    recommendedAction: rec?.action ?? null,
    suggestedQuantity: rec?.suggestedQuantity ?? null,
    priority: null,
    modelAccuracy: null,
    dataStatus: summary.expectedDemand != null ? "estimated" : null,
    stockDataStatus: inventory.length ? "verified" : null,
    coverage: {
      status: summary.status,
      coveredDays: summary.coveredDays,
      periodDays: days
    },
    forecast: summary.selected.map(serialize),
    recommendation: rec
  };
}

export const getDemandOverview = async (
  tenantId: string,
  periodDays: number,
  productId: string,
  userId: string
) => {
  const now = new Date();
  const start = utcDay(now);
  const end = addDays(start, periodDays - 1);

  // Load one preceding horizon as well as the requested horizon. Interval-based
  // forecasts need the preceding comparable period to derive increase/decrease/
  // stable without inventing daily values from an aggregate forecast.
  const comparisonStart = addDays(start, -periodDays);
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
      now
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
    ? completeRows.reduce(
        (sum, product) => sum + product.expectedDemand!,
        0
      )
    : null;

  const points = Array.from({ length: periodDays }, (_, index) => {
    const date = dayKey(addDays(start, index));
    const values = rows.map((product) =>
      product.coverage.status === "overlapping"
        ? null
        : product.forecast.find(
              (forecast) =>
                forecast.date === date && forecast.endDate === date
            )?.forecastedDemand ?? null
    );
    const coveredProducts = values.filter((value) => value != null).length;

    // A stored multi-day interval is a horizon total, not a daily value. Keep
    // daily chart points null unless every selected product has an actual daily
    // forecast for that date.
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

  const hasTrend = rows.some((product) => product.trend != null);

  return {
    companyId: tenantId,
    generatedAt: now.toISOString(),
    filters: {
      productId,
      periodDays,
      startDate: dayKey(start),
      endDate: dayKey(end),
      timeZone: "UTC"
    },
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
        dataStatus: total == null ? null : "estimated",
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
        ? "estimated"
        : null
    },
    forecasts: rows.map(({ forecast, recommendation: _recommendation, ...product }) =>
      product
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
  const start = utcDay(now);
  const end = addDays(start, periodDays - 1);
  const historyStart = addDays(start, -30);

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
    now
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

  const future = latestForecasts(snapshot.forecasts, now).filter((forecast) => {
    const window = forecastWindow(forecast)!;
    return window.start <= end && window.end >= start;
  });

  const historyRows = [...historical, ...future].map(serialize);
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

  const dailyForecasts = new Map(
    historyRows
      .filter((forecast) => forecast.date === forecast.endDate)
      .map((forecast) => [forecast.date, forecast])
  );

  const points = Array.from({ length: 30 + periodDays }, (_, index) => {
    const date = dayKey(addDays(historyStart, index));
    const row = dailyForecasts.get(date);
    const overlapping = historyRows.some(
      (forecast) =>
        forecast.date !== forecast.endDate &&
        forecast.date <= date &&
        forecast.endDate >= date
    );

    return {
      date,
      actual: actuals.get(date) ?? null,
      forecast: overlapping ? null : row?.forecastedDemand ?? null,
      lower: overlapping ? null : row?.lowerBound ?? null,
      upper: overlapping ? null : row?.upperBound ?? null
    };
  });

  return {
    companyId: tenantId,
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
        dataStatus: summary.dataStatus,
        format: "range"
      },
      {
        id: "modelAccuracy",
        value: null,
        dataStatus: null,
        format: "percent"
      }
    ],
    chart: { points, dataStatus: summary.dataStatus },
    forecastHistory: historyRows,
    recommendation: summary.recommendation,
    aiInsight: null,
    modelPerformance: null,
    pipelineStatus: "unavailable"
  };
};
