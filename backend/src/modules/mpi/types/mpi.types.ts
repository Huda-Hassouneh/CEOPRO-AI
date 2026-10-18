export type MpiSubjectType = "PRODUCT" | "COMPETITOR" | "BUSINESS";
export type MpiStatus = "OK" | "UNKNOWN";
export type MpiSampleStatus = "OK" | "LOW_SAMPLE_SIZE" | "UNKNOWN";

export type MpiLabelCounts = {
  positive: number;
  neutral: number;
  negative: number;
};

export type MpiSampleSize = {
  status: MpiSampleStatus;
  minimum_required: number;
  observed: number;
};

export type MpiReason = "NO_ELIGIBLE_REVIEWS" | "INSUFFICIENT_REVIEWS" | "MODEL_UNAVAILABLE";

export type MpiEvidence = {
  explanation: string | null;
  source_review_ids: string[];
  source_scope: "submitted_sample";
  observation_period: { start: string | null; end: string | null };
  collection_methods: string[];
  eligible_review_count: number;
  sample_limit: number;
  sentiment_model: string | null;
  model_revision: string | null;
};

export type MpiSummaryContext = {
  subject_type: MpiSubjectType;
  subject_id: string | null;
  as_of: string;
  review_count: number;
  confidence_score: number | null;
  analysis_performed: boolean;
  evidence: MpiEvidence;
};

export type AiMpiUnknownResponse = MpiSummaryContext & {
  status: "UNKNOWN";
  evidence_id: string | null;
  sample_size: MpiSampleSize;
  reason: MpiReason;
  label_counts: MpiLabelCounts | null;
};

export type AiMpiSuccessResponse = MpiSummaryContext & {
  status: "OK";
  evidence_id: string | null;
  mpi: number;
  sample_size: MpiSampleSize;
  weighted_sentiment_score: number;
  volume_confidence: number;
  review_count: number;
  avg_recency_weight: number;
  avg_reliability_weight: number;
  label_counts: MpiLabelCounts;
  reason: null;
};

export type AiMpiSummaryResponse =
  | AiMpiUnknownResponse
  | AiMpiSuccessResponse;

export type MpiClientError = Error & {
  name: "AiIntegrationError";
  kind: string;
  upstreamStatus?: number;
};
