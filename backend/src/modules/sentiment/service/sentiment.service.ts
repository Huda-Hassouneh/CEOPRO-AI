import {
  getRemainingUsage,
  incrementUsage
} from "../../features/repo/usage.repo.js";
import { requestSentimentClassification } from "../client/sentiment.client.js";
import {
  getPendingReviews,
  getSentimentAggregate,
  saveSentimentResults
} from "../repo/sentiment.repo.js";
import type {
  AiSentimentSummaryResponse,
  SentimentAnalyzeResult,
  SentimentServiceError,
  SentimentSubjectType
} from "../types/sentiment.types.js";

const DEFAULT_BATCH_SIZE = 100;
const MODEL_BATCH_SIZE = 64;
const MINIMUM_SUMMARY_SIZE = 5;

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
  userId: string;
  requestedBatchSize?: number;
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

  const pending = await getPendingReviews({
    tenantId: input.tenantId,
    userId: input.userId,
    limit: allowedBatchSize
  });
  let analyzedCount = 0;

  for (let offset = 0; offset < pending.length; offset += MODEL_BATCH_SIZE) {
    const batch = pending.slice(offset, offset + MODEL_BATCH_SIZE);
    const response = await requestSentimentClassification(
      batch.map((review) => review.review_text)
    );
    const rows = response.results.map((result, index) => {
      const review = batch[index];
      if (!review || result.text !== review.review_text) {
        throw createSentimentServiceError(
          "AI_PROCESSED_OVER_LIMIT",
          "AI sentiment output did not preserve the submitted text order."
        );
      }
      return {
        reviewId: review.review_id,
        score: result.positive_probability - result.negative_probability,
        label: result.label,
        positiveProbability: result.positive_probability,
        neutralProbability: result.neutral_probability,
        negativeProbability: result.negative_probability,
        confidence: result.confidence,
        modelVersion: result.model_version
      };
    });

    await saveSentimentResults({
      tenantId: input.tenantId,
      userId: input.userId,
      results: rows
    });
    await incrementUsage(input.tenantId, "sentiment_analysis", rows.length);
    analyzedCount += rows.length;
  }

  return {
    status: "OK",
    analyzed_count: analyzedCount,
    requested_batch_size: requestedBatchSize,
    allowed_batch_size: allowedBatchSize
  };
}

export async function getSentimentSummary(input: {
  tenantId: string;
  userId: string;
  subjectType: SentimentSubjectType;
  subjectId?: string;
  countryContext?: string;
}): Promise<AiSentimentSummaryResponse> {
  if (input.countryContext) {
    throw createSentimentServiceError(
      "UNSUPPORTED_COUNTRY_FILTER",
      "Country-filtered sentiment summaries are not available because review records do not store a country."
    );
  }

  const aggregate = await getSentimentAggregate(input);
  if (aggregate.count < MINIMUM_SUMMARY_SIZE) {
    return {
      status: "UNKNOWN",
      evidence_id: null,
      sample_size: {
        status: "LOW_SAMPLE_SIZE",
        minimum_required: MINIMUM_SUMMARY_SIZE
      }
    };
  }

  return {
    status: "OK",
    evidence_id: null,
    sentiment_score: aggregate.averageScore ?? 0,
    label_counts: aggregate.labelCounts,
    sample_size: {
      status: "OK",
      minimum_required: MINIMUM_SUMMARY_SIZE
    }
  };
}
