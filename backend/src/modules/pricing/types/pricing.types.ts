export type PricingAction = "raise" | "lower" | "hold";
export type PricingStatus = "OK" | "UNKNOWN";

export type AiPricingUnknownResponse = {
  status: "UNKNOWN";
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
};

export type AiPricingResult =
  | AiPricingUnknownResponse
  | AiPricingSuccessResponse;

export type AiPricingRequest = {
  product: {
    product_name: string;
    current_price: number;
    currency: string;
    cost_price: number | null;
  };
  competitorPrices: Array<{
    competitor_name: string;
    price: number;
    currency: string;
    observed_at: string;
  }>;
  exchangeRates: Array<{
    from_currency: string;
    to_currency: string;
    rate: number;
    as_of: string;
    source: string;
  }> | null;
};

export type PricingProductContext = {
  productId: string;
  productName: string;
  currentPrice: number;
  costPrice: number | null;
  currency: string;
  version: number;
};

export type MarketPricePoint = {
  competitorPriceId: string;
  mappingId: string;
  competitorId: string;
  competitorName: string;
  price: number;
  currency: string;
  observedAt: Date;
};

export type PricingRate = {fromCurrency:string;toCurrency:string;rate:number;asOf:Date;source:string};
export type PricingSource = {
  competitor_price_id:string; mapping_id:string; competitor_id:string; competitor_name:string;
  original_price:number; original_currency:string; converted_price:number; currency:string;
  observed_at:string; conversion:{rate:number;as_of:string;source:string}|null;
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
  /** Server-enforced movement limit, as a fraction. */
  max_change_pct: number | null;
  /** Markup-on-cost floor, as a fraction; null when cost is unknown. */
  min_margin_pct: number | null;
  /** Server-computed cost floor in the product currency. */
  floor_price: number | null;
  explanation: string | null;
  evidence_id: string;
  outcome_id: string | null;
  currency: string;
  request_id: string;
  generated_at: string;
  sources: PricingSource[];
  reference_sources: PricingSource[];
  market_as_of: string;
  oldest_observation_at: string | null;
  market_freshness_days: number;
  fx_freshness_days: number;
  reason: string | null;
  charged: boolean;
  product_version: number;
  product_cost_price: number | null;
  guardrail_precedence: "cost_floor";
  movement_cap_overridden: boolean;
  explanation_i18n: {en:string;ar:string};
  provider_suggested_price: number | null;
  provider_adjusted: boolean;
  provider_explanation: string | null;
};

export type PricingClientError = Error & {
  name: "AiIntegrationError";
  kind: string;
  upstreamStatus?: number;
};

export type PricingServiceErrorCode = "PRODUCT_NOT_FOUND" | "INVALID_PRODUCT_PRICE" | "INVALID_REQUEST" | "REQUEST_CONFLICT" | "REQUEST_PENDING" | "REQUEST_FAILED" | "REQUEST_EXPIRED" | "SOURCE_CHANGED" | "INVALID_AI_RESULT";

export type PricingServiceError = Error & {
  name: "PricingServiceError";
  code: PricingServiceErrorCode;
};
