export type PricingAction = "raise" | "lower" | "hold";
export type PricingStatus = "OK" | "UNKNOWN";

export type AiPricingUnknownResponse = {
  status: "UNKNOWN";
  evidence_id: string;
};

export type AiPricingSuccessResponse = {
  status: "OK";
  action: PricingAction;
  current_price: number;
  suggested_price: number;
  guardrail_clamped: boolean;
  margin_guardrail_clamped: boolean | null;
  matched_competitor_count: number;
  confidence_score: number;
  evidence_id: string;
  outcome_id: string;
};

export type AiPricingResponse =
  | AiPricingUnknownResponse
  | AiPricingSuccessResponse;

export type PricingProductContext = {
  productId: string;
  currentPrice: number;
  currency: string;
};

export type MarketPricePoint = {
  competitorPriceId: string;
  mappingId: string;
  competitorId: string;
  price: number;
  currency: string;
  observedAt: Date;
};

export type MarketPriceStats = {
  min: number | null;
  max: number | null;
  average: number | null;
  median: number | null;
  count: number;
};

export type PricingEvidence = {
  evidenceId: string;
  explanationText: string | null;
  confidenceScore: number | null;
  generatedAt: Date | null;
};

export type PricingRecommendationResult = {
  status: PricingStatus;
  action: PricingAction | null;
  current_price: number;
  suggested_price: number | null;
  market_min: number | null;
  market_max: number | null;
  market_avg: number | null;
  market_median: number | null;
  matched_competitor_count: number;
  confidence_score: number | null;
  guardrail_clamped: boolean | null;
  margin_guardrail_clamped: boolean | null;
  /** Backward-compatible alias for guardrail_clamped. */
  clamped: boolean | null;
  /** Not exposed by the current CEOPRO AI API contract. */
  max_change_pct: null;
  /** Not exposed by the current CEOPRO AI API contract. */
  min_margin_pct: null;
  /** Not exposed by the current CEOPRO AI API contract. */
  floor_price: null;
  explanation: string | null;
  evidence_id: string;
  outcome_id: string | null;
  currency: string;
};

export type PricingClientError = Error & {
  name: "PricingClientError";
  upstreamStatus?: number;
};

export type PricingServiceErrorCode = "PRODUCT_NOT_FOUND";

export type PricingServiceError = Error & {
  name: "PricingServiceError";
  code: PricingServiceErrorCode;
};
