import { usableForecasts } from "../../forecasting/service/forecasting.policy.js";
import {
  finiteNumber,
  summarizeForecasts,
  utcDay,
  addDays,
  type ForecastRow
} from "../../forecasting/service/forecasting.calculations.js";

export function comparableMarketPrice<T extends { currency: string; observed_at: Date; scraped_price: unknown }>(
  observations: T[], currency: string, asOf: Date, maxAgeDays: number | null
): number | null {
  const observation = observations.filter((row) => row.currency === currency)
    .sort((left, right) => right.observed_at.getTime() - left.observed_at.getTime())[0];
  if (!observation) return null;
  const freshness = sourceFreshness(observation.observed_at, asOf, maxAgeDays);
  if (!freshness.timestamp || freshness.status === "stale") return null;
  const value = finiteNumber(observation.scraped_price);
  return value !== null && value > 0 ? value : null;
}

export class MarketProductNotFoundError extends Error {
  constructor() {
    super("Product not found");
    this.name = "MarketProductNotFoundError";
  }
}

export function selectMarketProduct<T extends { product_id: string }>(
  products: T[],
  requestedId?: string
): T | null {
  if (requestedId !== undefined) {
    const selected = products.find((product) => product.product_id === requestedId);
    if (!selected) throw new MarketProductNotFoundError();
    return selected;
  }
  return products[0] ?? null;
}

/** No age threshold is inferred from the user's 30/90-day reporting filter. */
export function sourceAgePolicy(raw?: string): number | null {
  if (!raw?.trim()) return null;
  const days = Number(raw);
  if (!Number.isFinite(days) || days <= 0) {
    throw new Error("MARKET_INTELLIGENCE_MAX_SOURCE_AGE_DAYS must be a positive number.");
  }
  return days;
}

export function sourceFreshness(
  value: Date | string | null | undefined,
  asOf: Date,
  maxAgeDays: number | null
) {
  const date = value == null ? null : new Date(value);
  const valid = date !== null && Number.isFinite(date.getTime()) && date <= asOf;
  const timestamp = valid ? date.toISOString() : null;
  const status = !valid
    ? "unknown"
    : maxAgeDays === null
      ? "not_assessed"
      : asOf.getTime() - date.getTime() > maxAgeDays * 86_400_000
        ? "stale"
        : "current";
  return { timestamp, status, maxAgeDays };
}

export type MarketDataStatus = "verified" | "derived" | "partial" | "stale" | "unavailable";

export function aggregateMarketStatus(statuses: Array<string | null | undefined>): MarketDataStatus {
  if (!statuses.length || statuses.every((status) => !status || status === "unavailable")) {
    return "unavailable";
  }
  if (statuses.every((status) => status === "stale")) return "stale";
  if (statuses.some((status) => !status || ["partial", "unavailable", "stale"].includes(status))) {
    return "partial";
  }
  return statuses.includes("derived") ? "derived" : "verified";
}

/** Compare complete product horizons; never prorate an aggregate or sum overlaps. */
export function summarizeMarketDemand<T extends ForecastRow & { product_id: string }>(
  rows: T[],
  productIds: string[],
  asOf: Date,
  days: number,
  maxAgeDays: number | null
) {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const freshness = sourceFreshness(row.created_at, asOf, maxAgeDays);
    if (freshness.status === "stale" || (maxAgeDays !== null && freshness.status === "unknown")) continue;
    const group = groups.get(row.product_id) ?? [];
    group.push(row);
    groups.set(row.product_id, group);
  }
  return new Map(productIds.map((productId) => [
    productId,
    summarizeForecasts(usableForecasts(groups.get(productId) ?? [], asOf), addDays(utcDay(asOf), 1), days, asOf)
  ]));
}
