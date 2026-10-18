import { forecastWindow, type ForecastRow } from "./forecasting.calculations.js";
import { inventoryContext, sourceFreshness } from "./forecasting.policy.js";

type RecommendationForecast = ForecastRow & {
  recommendation_outcomes: Array<{
    recommendation_id: string; recommended_action: string | null; created_at: Date | null;
    forecast_id?: string | null;
  }>;
};

/** Validate an existing saved decision; this does not generate an AI action. */
export function supportedInventoryRecommendation(
  rows: RecommendationForecast[], stock: ReturnType<typeof inventoryContext>,
  coverage: string, expectedDemand: number | null, asOf: Date
) {
  const unavailable = (reason: string) => ({ recommendation: null, status: { status: "unavailable", reason } });
  if (stock.currentStock === null) return unavailable(stock.reason ?? "INVALID_INVENTORY");
  if (!stock.freshness.timestamp || !stock.latestUpdatedAt) return unavailable("UNDATED_INVENTORY");
  if (coverage !== "complete" || expectedDemand === null || !Number.isFinite(expectedDemand) || expectedDemand < 0) return unavailable("INCOMPLETE_FORECAST");
  // A saved action for one daily row cannot be applied to a combined horizon.
  if (rows.length !== 1) return unavailable("NO_HORIZON_RECOMMENDATION");
  const forecast = rows[0]!;
  const result = [...forecast.recommendation_outcomes].sort((a, b) =>
    (b.created_at?.getTime() ?? 0) - (a.created_at?.getTime() ?? 0) ||
    b.recommendation_id.localeCompare(a.recommendation_id)
  )[0];
  if (!result) return unavailable("NO_STORED_RECOMMENDATION");
  const aliases: Record<string, "restock" | "reduce" | "monitor"> = {
    restock: "restock", restock_now: "restock", reduce: "reduce", reduce_order: "reduce", monitor: "monitor"
  };
  const actionKey = result.recommended_action?.trim().toLowerCase() ?? "";
  const action = Object.hasOwn(aliases, actionKey) ? aliases[actionKey] : undefined;
  const window = forecastWindow(forecast);
  if (!action || !window || ("forecast_id" in result && result.forecast_id !== forecast.forecast_id)) return unavailable("INVALID_RECOMMENDATION");
  if (!forecast.created_at || !Number.isFinite(forecast.created_at.getTime()) || forecast.created_at > asOf ||
      !result.created_at || !Number.isFinite(result.created_at.getTime()) ||
      result.created_at > asOf || result.created_at < forecast.created_at ||
      ["stale", "unavailable"].includes(sourceFreshness(result.created_at, asOf).status)) return unavailable("OUTDATED_RECOMMENDATION");
  if (result.created_at < new Date(stock.latestUpdatedAt)) return unavailable("STOCK_CHANGED");
  if (action === "restock" && stock.safetyStock === null) return unavailable("MISSING_SAFETY_STOCK");
  const suggestedQuantity = action === "restock"
    ? Math.ceil(Math.max(0, expectedDemand + stock.safetyStock! - stock.currentStock)) : null;
  if (suggestedQuantity !== null && (!Number.isSafeInteger(suggestedQuantity) || suggestedQuantity === 0)) return unavailable("INCONSISTENT_RECOMMENDATION");
  const features = forecast.features_used && typeof forecast.features_used === "object" && !Array.isArray(forecast.features_used)
    ? forecast.features_used as Record<string, unknown> : {};
  const confidence = features.confidence_score;
  return { status: { status: "available", reason: null }, recommendation: {
    id: result.recommendation_id, action, suggestedQuantity, priority: null,
    startDate: window.start.toISOString().slice(0, 10), targetDate: window.end.toISOString().slice(0, 10),
    modelAccuracy: null, confidenceScore: typeof confidence === "number" && Number.isFinite(confidence) && confidence >= 0 && confidence <= 1 ? confidence : null,
    dataStatus: "estimated", quantityDataStatus: suggestedQuantity === null ? null : "derived",
    generatedAt: result.created_at.toISOString(), source: "stored_recommendation", forecastId: forecast.forecast_id,
    stockUpdatedAt: stock.latestUpdatedAt, oldestStockUpdatedAt: stock.freshness.timestamp,
    warehouseCount: stock.warehouseCount,
    calculation: suggestedQuantity === null ? null : { expectedDemand, currentStock: stock.currentStock, safetyStock: stock.safetyStock }
  } };
}
