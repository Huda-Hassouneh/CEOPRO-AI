import {
  getRemainingUsage,
  incrementUsage
} from "../../features/repo/usage.repo.js";
import {
  requestAnalyzePendingSentiment,
  requestSentimentSummary
} from "../client/sentiment.client.js";
import type {
  AiSentimentSummaryResponse,
  SentimentAnalyzeResult,
  SentimentServiceError,
  SentimentSubjectType
} from "../types/sentiment.types.js";

const DEFAULT_BATCH_SIZE = 100;

function createSentimentServiceError(
  code: SentimentServiceError["code"],
  message: string,
  details?: unknown
): SentimentServiceError {
  const error = new Error(message) as SentimentServiceError;
  error.name = "SentimentServiceError";
  error.code = code;
  error.details = details;
  return error;
}

export function isSentimentServiceError(
  error: unknown
): error is SentimentServiceError {
  return error instanceof Error && error.name === "SentimentServiceError";
}

export async function analyzePendingSentiment(input: {
  tenantId: string;
  requestedBatchSize?: number;
  authorization: string;
}): Promise<SentimentAnalyzeResult> {
  const requestedBatchSize = input.requestedBatchSize ?? DEFAULT_BATCH_SIZE;
  const usage = await getRemainingUsage(input.tenantId, "sentiment_analysis");

  if (!usage) {
    throw createSentimentServiceError(
      "ENTITLEMENT_NOT_AVAILABLE",
      "Sentiment analysis is not available for this subscription."
    );
  }

  const allowedBatchSize =
    usage.remaining === null
      ? requestedBatchSize
      : Math.max(
          0,
          Math.min(requestedBatchSize, Math.floor(Number(usage.remaining)))
        );

  if (allowedBatchSize <= 0) {
    throw createSentimentServiceError(
      "QUOTA_EXCEEDED",
      "Sentiment analysis quota has been reached.",
      {
        current_usage: usage.currentUsage,
        limit: usage.limit,
        remaining: 0
      }
    );
  }

  const ai = await requestAnalyzePendingSentiment({
    batchSize: allowedBatchSize,
    authorization: input.authorization
  });

  if (ai.analyzed_count > allowedBatchSize) {
    throw createSentimentServiceError(
      "AI_PROCESSED_OVER_LIMIT",
      "AI sentiment service processed more records than the allowed batch size.",
      {
        analyzed_count: ai.analyzed_count,
        allowed_batch_size: allowedBatchSize
      }
    );
  }

  if (ai.analyzed_count > 0) {
    await incrementUsage(
      input.tenantId,
      "sentiment_analysis",
      ai.analyzed_count
    );
  }

  return {
    status: ai.status,
    analyzed_count: ai.analyzed_count,
    requested_batch_size: requestedBatchSize,
    allowed_batch_size: allowedBatchSize
  };
}

export async function getSentimentSummary(input: {
  subjectType: SentimentSubjectType;
  subjectId?: string;
  countryContext?: string;
  authorization: string;
}): Promise<AiSentimentSummaryResponse> {
  return requestSentimentSummary(input);
}
