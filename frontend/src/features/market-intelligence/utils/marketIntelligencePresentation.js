import { getApiError, getApiErrorMessage } from "../../../shared/lib/apiErrorCore.js";

export function pricingErrorMessage(error, t) {
  const apiError = getApiError(error);
  const reason=apiError.details?.reason;
  const keys={REQUEST_PENDING:'pending',REQUEST_FAILED:'requestFailed',REQUEST_EXPIRED:'requestFailed',REQUEST_CONFLICT:'requestConflict',
    SOURCE_CHANGED:'sourceChanged',INVALID_PRODUCT_PRICE:'invalidProduct',INVALID_AI_RESULT:'invalidResult'};
  if(keys[reason])return t(`marketMain.pricingFix.errors.${keys[reason]}`);
  if (apiError.details?.reason === "QUOTA_EXHAUSTED") return t("marketMain.error.pricingQuotaExhausted");
  if (apiError.details?.reason === "FEATURE_NOT_INCLUDED") return t("marketMain.error.pricingNotIncluded");
  return getApiErrorMessage(error, t, { fallbackKey: "marketMain.error.description" });
}

export function aggregateSectionStatus(rows) {
  const statuses = (rows ?? []).map((row) => row.dataStatus ?? "unavailable");
  if (!statuses.length || statuses.every((status) => status === "unavailable")) return "unavailable";
  if (statuses.every((status) => status === "stale")) return "stale";
  if (statuses.some((status) => ["unavailable", "partial", "stale"].includes(status))) return "partial";
  return statuses.includes("derived") ? "derived" : "verified";
}

export function buildPricingRows({ overviewRows, recommendation, selectedProduct }) {
  if (!selectedProduct) return [];
  const baseRow = overviewRows?.find((row) => row.productId === selectedProduct.id) ?? null;
  if (!recommendation) {
    if (!baseRow) return [];
    return [{ ...baseRow, action: null, suggestedPrice: null, explanation: null,
      confidenceScore: null, guardrailClamped: null, marginGuardrailClamped: null,
      evidenceId: null, outcomeId: null }];
  }
  const currency = recommendation.currency ?? selectedProduct.currency;
  const compatibleBase = currency?.toUpperCase() === selectedProduct.currency?.toUpperCase() ? baseRow : null;
  return [{
    ...(compatibleBase ?? {}),
    id: `price-rec-${selectedProduct.id}`,
    productId: selectedProduct.id,
    productName: selectedProduct.name,
    status: recommendation.status,
    currentPrice: recommendation.current_price ?? compatibleBase?.currentPrice ?? null,
    action: recommendation.status === "OK" ? recommendation.action : null,
    suggestedPrice: recommendation.status === "OK" ? recommendation.suggested_price : null,
    marketMin: 'market_min' in recommendation?recommendation.market_min:compatibleBase?.marketMin??null,
    marketMax: 'market_max' in recommendation?recommendation.market_max:compatibleBase?.marketMax??null,
    marketAverage: 'market_avg' in recommendation?recommendation.market_avg:compatibleBase?.marketAverage??null,
    marketMedian: 'market_median' in recommendation?recommendation.market_median:compatibleBase?.marketMedian??null,
    matchedCompetitors: recommendation.matched_competitor_count ?? null,
    explanation: recommendation.explanation_i18n ?? recommendation.explanation ?? null,
    confidenceScore: recommendation.confidence_score ?? null,
    guardrailClamped: recommendation.guardrail_clamped ?? null,
    marginGuardrailClamped: recommendation.margin_guardrail_clamped ?? null,
    evidenceId: recommendation.evidence_id ?? null,
    outcomeId: recommendation.outcome_id ?? null,
    currency,
    generatedAt: recommendation.generated_at ?? null,
    dataStatus: recommendation.is_stale ? "stale" : recommendation.status === "OK" ? "derived" : "unavailable"
  }];
}

/** Fail closed for optional features; regular market statistics remain exportable. */
export function prepareMarketExport(data, access, pricingRows) {
  const marketPerception = access.marketPerception === true;
  const aiPricing = access.aiPricing === true;
  return {
    ...data,
    featureAccess: { ...data.featureAccess, marketPerception, aiPricing },
    competitors: (data.competitors ?? []).map((row) => marketPerception ? row : {
      ...row, marketPerception: null, marketPerceptionScore: null,
      marketPerceptionSummary: null, marketPerceptionStatus: "NOT_INCLUDED"
    }),
    pricingRecommendations: (pricingRows ?? data.pricingRecommendations ?? []).map((row) => aiPricing ? row : {
      ...row, status: null, action: null, suggestedPrice: null, explanation: null,
      confidenceScore: null, guardrailClamped: null, marginGuardrailClamped: null,
      evidenceId: null, outcomeId: null
    })
  };
}
