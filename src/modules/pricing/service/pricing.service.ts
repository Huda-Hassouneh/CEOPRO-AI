import { incrementUsage } from "../../features/repo/usage.repo.js";
import {
  readPricingExplanation,
  requestPricingRecommendation
} from "../client/pricing.client.js";
import {
  getEligibleMarketPrices,
  getExchangeRates,
  getProductPricingContext,
  persistPricingRecommendation
} from "../repo/pricing.repo.js";
import type {
  MarketPriceStats,
  PricingRecommendationResult,
  PricingServiceError
} from "../types/pricing.types.js";

const MARKET_FRESHNESS_DAYS = 30;
const DAY_MS = 24 * 60 * 60 * 1000;

function createPricingServiceError(
  code: PricingServiceError["code"],
  message: string
): PricingServiceError {
  const error = new Error(message) as PricingServiceError;
  error.name = "PricingServiceError";
  error.code = code;
  return error;
}

export function isPricingServiceError(
  error: unknown
): error is PricingServiceError {
  return error instanceof Error && error.name === "PricingServiceError";
}

function summarizeMarketPrices(prices: number[]): MarketPriceStats {
  const values = prices.filter(
    (value) => Number.isFinite(value) && value >= 0
  );
  if (values.length === 0) {
    return { min: null, max: null, average: null, median: null, count: 0 };
  }

  const sorted = [...values].sort((a, b) => a - b);
  const sum = sorted.reduce((total, value) => total + value, 0);
  const middle = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? (sorted[middle - 1] + sorted[middle]) / 2
      : sorted[middle];
  return {
    min: sorted[0],
    max: sorted[sorted.length - 1],
    average: sum / sorted.length,
    median,
    count: sorted.length
  };
}

export async function getPricingRecommendation(input: {
  tenantId: string;
  userId: string;
  productId: string;
}): Promise<PricingRecommendationResult> {
  const product = await getProductPricingContext(
    input.tenantId,
    input.userId,
    input.productId
  );
  if (!product) {
    throw createPricingServiceError(
      "PRODUCT_NOT_FOUND",
      "Product was not found for this tenant."
    );
  }

  const observedBefore = new Date();
  const observedAfter = new Date(
    observedBefore.getTime() - MARKET_FRESHNESS_DAYS * DAY_MS
  );
  const marketPoints = await getEligibleMarketPrices({
    tenantId: input.tenantId,
    userId: input.userId,
    productId: input.productId,
    observedAfter,
    observedBefore
  });
  const exchangeRates = await getExchangeRates({
    fromCurrencies: marketPoints.map((point) => point.currency),
    toCurrency: product.currency
  });

  // Product and market inputs come from CEOPRO's tenant-scoped database. The
  // Gradio API only returns a recommendation; its response cannot replace the
  // server's product ownership, price, currency, or cost data.
  const ai = await requestPricingRecommendation({
    product: {
      product_name: product.productName,
      current_price: product.currentPrice,
      currency: product.currency,
      cost_price: product.costPrice
    },
    competitorPrices: marketPoints.map((point) => ({
      competitor_name: point.competitorName,
      price: point.price,
      currency: point.currency,
      observed_at: point.observedAt.toISOString().slice(0, 10)
    })),
    exchangeRates:
      exchangeRates.length > 0
        ? exchangeRates.map((rate) => ({
            from_currency: rate.fromCurrency,
            to_currency: rate.toCurrency,
            rate: rate.rate,
            as_of: rate.asOf.toISOString().slice(0, 10),
            source: rate.source
          }))
        : null
  });

  const result = ai.result;
  const sameCurrencyPrices = marketPoints.filter(
    (point) => point.currency === product.currency
  );
  const market = summarizeMarketPrices(
    sameCurrencyPrices.map((point) => point.price)
  );
  const status = result.status;
  const action = result.status === "OK" ? result.action : null;
  const suggestedPrice = result.status === "OK" ? result.suggested_price : null;
  const matchedCompetitorCount =
    result.status === "OK" ? result.matched_competitor_count : 0;
  const confidenceScore =
    result.status === "OK" ? result.confidence_score : null;
  const guardrailClamped =
    result.status === "OK" ? result.guardrail_clamped : null;
  const marginGuardrailClamped =
    result.status === "OK" ? result.margin_guardrail_clamped : null;

  const persisted = await persistPricingRecommendation({
    tenantId: input.tenantId,
    userId: input.userId,
    productId: product.productId,
    status,
    action,
    currentPrice: product.currentPrice,
    suggestedPrice,
    confidenceScore,
    explanationText: readPricingExplanation(ai),
    matchedCompetitorCount,
    guardrailClamped,
    marginGuardrailClamped
  });

  await incrementUsage(input.tenantId, "ai_pricing");

  return {
    status,
    action,
    current_price: product.currentPrice,
    suggested_price: suggestedPrice,
    market_min: market.min,
    market_max: market.max,
    market_avg: market.average,
    market_median: market.median,
    matched_competitor_count: matchedCompetitorCount,
    confidence_score: confidenceScore,
    guardrail_clamped: guardrailClamped,
    margin_guardrail_clamped: marginGuardrailClamped,
    clamped: guardrailClamped,
    max_change_pct: null,
    min_margin_pct: null,
    floor_price: null,
    explanation: readPricingExplanation(ai),
    evidence_id: persisted.evidenceId,
    outcome_id: persisted.outcomeId,
    currency: product.currency
  };
}
