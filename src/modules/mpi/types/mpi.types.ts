export type MpiSubjectType = "PRODUCT" | "COMPETITOR" | "BUSINESS";
export type MpiStatus = "OK" | "UNKNOWN";
export type MpiSampleStatus = "OK" | "LOW_SAMPLE_SIZE";

export type MpiLabelCounts = {
  positive: number;
  neutral: number;
  negative: number;
};

export type MpiSampleSize = {
  status: MpiSampleStatus;
  minimum_required: number;
};

export type AiMpiUnknownResponse = {
  status: "UNKNOWN";
  evidence_id: string | null;
  sample_size: MpiSampleSize;
};

export type AiMpiSuccessResponse = {
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
};

export type AiMpiSummaryResponse =
  | AiMpiUnknownResponse
  | AiMpiSuccessResponse;

export type MpiClientError = Error & {
  name: "AiIntegrationError";
  kind: string;
  upstreamStatus?: number;
};
