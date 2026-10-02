import { incrementUsage } from "../../features/repo/usage.repo.js";
import { requestPricingRecommendation } from "../client/pricing.client.js";
import {
  getLatestEligibleMarketPrices,
  getPricingEvidence,
  getProductPricingContext
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
    return {
      min: null,
      max: null,
      average: null,
      median: null,
      count: 0
    };
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
  authorization: string;
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

  // Trigger the canonical AI pricing pipeline first. The CEOPRO AI API is the
  // authoritative contract for action/suggested price/confidence/guardrails.
  const ai = await requestPricingRecommendation({
    productId: input.productId,
    authorization: input.authorization
  });

  // Backend-derived market context deliberately does not depend on undocumented
  // AI response fields. It uses the same documented pricing-input constraints
  // available in our schema: active/tracked mappings, available exact ALLOWED
  // same-currency observations inside the 30-day freshness window.
  //
  // We keep every eligible observation in the window rather than inventing a
  // "latest-only" rule that the AI team's pricing contract does not specify.
  const [marketPoints, evidence] = await Promise.all([
    getLatestEligibleMarketPrices({
      tenantId: input.tenantId,
      userId: input.userId,
      productId: input.productId,
      currency: product.currency,
      observedAfter,
      observedBefore
    }),
    // The AI pipeline persists evidence and returns evidence_id. Read the
    // canonical explanation from the DB instead of expecting an undocumented
    // `explanation` field from POST /pricing/recommend.
    getPricingEvidence(
      input.tenantId,
      input.userId,
      ai.evidence_id
    )
  ]);

  const market = summarizeMarketPrices(
    marketPoints.map((point) => point.price)
  );

  await incrementUsage(input.tenantId, "ai_pricing");

  if (ai.status === "UNKNOWN") {
    return {
      status: "UNKNOWN",
      action: null,
      current_price: product.currentPrice,
      suggested_price: null,
      market_min: market.min,
      market_max: market.max,
      market_avg: market.average,
      market_median: market.median,
      matched_competitor_count: 0,
      confidence_score: evidence?.confidenceScore ?? null,
      guardrail_clamped: null,
      margin_guardrail_clamped: null,
      clamped: null,
      max_change_pct: null,
      min_margin_pct: null,
      floor_price: null,
      explanation: evidence?.explanationText ?? null,
      evidence_id: ai.evidence_id,
      outcome_id: null,
      currency: product.currency
    };
  }

  return {
    status: "OK",
    action: ai.action,
    current_price: ai.current_price,
    suggested_price: ai.suggested_price,
    market_min: market.min,
    market_max: market.max,
    market_avg: market.average,
    market_median: market.median,
    matched_competitor_count: ai.matched_competitor_count,
    confidence_score: ai.confidence_score,
    guardrail_clamped: ai.guardrail_clamped,
    margin_guardrail_clamped: ai.margin_guardrail_clamped,
    clamped: ai.guardrail_clamped,
    max_change_pct: null,
    min_margin_pct: null,
    floor_price: null,
    explanation: evidence?.explanationText ?? null,
    evidence_id: ai.evidence_id,
    outcome_id: ai.outcome_id,
    currency: product.currency
  };
}
