import { dayKey, finiteNumber, utcDay, type ForecastRow } from "./forecasting.calculations.js";
import type { ForecastTransactionInput } from "../client/forecasting.client.js";

export class ForecastAccessError extends Error {
  constructor(readonly code: "SUBSCRIPTION_NOT_FOUND" | "FEATURE_NOT_INCLUDED") {
    super("Demand Prediction is not available in the active subscription.");
  }
}

export function historyIsUsable(rows: ForecastTransactionInput[], asOf: Date) {
  const dates = new Set<string>();
  return rows.every((row) => {
    const date = new Date(`${row.transaction_date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.transaction_date) || !Number.isFinite(date.getTime()) ||
        dayKey(date) !== row.transaction_date || date > utcDay(asOf) || dates.has(row.transaction_date) ||
        !Number.isSafeInteger(row.quantity) || row.quantity < 0 ||
        !Number.isFinite(row.unit_price) || row.unit_price < 0) return false;
    dates.add(row.transaction_date);
    return true;
  });
}

export function sourceFreshness(date: Date | null | undefined, asOf: Date) {
  const configured = process.env.FORECASTING_MAX_SOURCE_AGE_DAYS?.trim();
  const maxAgeDays = configured ? Number(configured) : null;
  if (maxAgeDays !== null && (!Number.isFinite(maxAgeDays) || maxAgeDays <= 0)) {
    throw new Error("FORECASTING_MAX_SOURCE_AGE_DAYS must be a positive number.");
  }
  const valid = date && Number.isFinite(date.getTime()) && date <= asOf;
  const ageDays = valid ? (asOf.getTime() - date.getTime()) / 86_400_000 : null;
  return {
    status: maxAgeDays === null ? "not_assessed" : ageDays === null ? "unavailable" : ageDays > maxAgeDays ? "stale" : "fresh",
    timestamp: valid ? date.toISOString() : null, ageDays, maxAgeDays
  };
}

export function usableForecasts<T extends ForecastRow>(rows: T[], asOf: Date) {
  return rows.filter((row) => !["stale", "unavailable"].includes(sourceFreshness(row.created_at, asOf).status));
}

export function inventoryContext(rows: Array<{ stock_quantity: number; safety_stock?: unknown; updated_at?: Date | null; warehouse_location?: string | null }>, asOf: Date) {
  const stock = rows.map((row) => finiteNumber(row.stock_quantity));
  const safety = rows.map((row) => finiteNumber(row.safety_stock));
  const dates = rows.map((row) => row.updated_at).filter((date): date is Date => date instanceof Date && Number.isFinite(date.getTime()));
  const validDates = dates.length === rows.length && dates.length > 0 && dates.every((date) => date <= asOf);
  const oldest = validDates ? new Date(Math.min(...dates.map((date) => date.getTime()))) : null;
  const newest = validDates ? new Date(Math.max(...dates.map((date) => date.getTime()))) : null;
  const freshness = sourceFreshness(oldest, asOf);
  const warehouses = rows.filter((row) => "warehouse_location" in row).map((row) =>
    row.warehouse_location?.trim().toLocaleLowerCase("en-US") || ""
  );
  const duplicateWarehouse = new Set(warehouses).size !== warehouses.length;
  const invalidDate = rows.some((row) => row.updated_at != null &&
    (!(row.updated_at instanceof Date) || !Number.isFinite(row.updated_at.getTime()) || row.updated_at > asOf));
  const usable = !duplicateWarehouse && !invalidDate && !["stale", "unavailable"].includes(freshness.status);
  const sum = (values: Array<number | null>) => {
    if (!usable || !values.length || !values.every((value) => value !== null && Number.isSafeInteger(value) && value >= 0)) return null;
    const total = values.reduce<number>((sum, value) => sum + value!, 0);
    return Number.isSafeInteger(total) ? total : null;
  };
  const currentStock = sum(stock);
  return { currentStock, safetyStock: sum(safety), freshness,
    warehouseCount: rows.length, latestUpdatedAt: newest?.toISOString() ?? null,
    reason: !rows.length ? "MISSING_INVENTORY" : duplicateWarehouse ? "DUPLICATE_WAREHOUSE" : invalidDate ? "INVALID_STOCK_DATE" :
      freshness.status === "stale" ? "STALE_INVENTORY" : freshness.status === "unavailable" ? "UNDATED_INVENTORY" : currentStock === null ? "INVALID_INVENTORY" : null };
}
