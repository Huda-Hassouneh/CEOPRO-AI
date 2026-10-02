export type SentimentSubjectType = "PRODUCT" | "COMPETITOR" | "BUSINESS";
export type SentimentSummaryStatus = "OK" | "UNKNOWN";
export type SentimentSampleStatus = "OK" | "LOW_SAMPLE_SIZE";

export type SentimentLabelCounts = {
  positive: number;
  neutral: number;
  negative: number;
};

export type SentimentSampleSize = {
  status: SentimentSampleStatus;
  minimum_required: number;
};

export type AiSentimentUnknownResponse = {
  status: "UNKNOWN";
  evidence_id: string;
  sample_size: {
    status: "LOW_SAMPLE_SIZE";
    minimum_required: number;
  };
};

export type AiSentimentSuccessResponse = {
  status: "OK";
  evidence_id: string;
  sentiment_score: number;
  label_counts: SentimentLabelCounts;
  sample_size: SentimentSampleSize;
};

export type AiSentimentSummaryResponse =
  | AiSentimentUnknownResponse
  | AiSentimentSuccessResponse;

export type AiSentimentAnalyzePendingResponse = {
  status: "OK";
  analyzed_count: number;
};

export type SentimentAnalyzeResult = {
  status: "OK";
  analyzed_count: number;
  requested_batch_size: number;
  allowed_batch_size: number;
};

export type SentimentClientError = Error & {
  name: "SentimentClientError";
  upstreamStatus?: number;
};

export type SentimentServiceErrorCode =
  | "ENTITLEMENT_NOT_AVAILABLE"
  | "QUOTA_EXCEEDED"
  | "AI_PROCESSED_OVER_LIMIT";

export type SentimentServiceError = Error & {
  name: "SentimentServiceError";
  code: SentimentServiceErrorCode;
  details?: unknown;
};
