import { requestMarketIntelligence } from "../client/mpi.client.js";
import { getReviewsForMpi, persistMpiEvidence } from "../repo/mpi.repo.js";
import type {
  AiMpiSummaryResponse,
  MpiSubjectType
} from "../types/mpi.types.js";

const MINIMUM_REVIEW_COUNT = 5;

function toCollectionMethod(
  value: string
): "PUBLIC_API" | "PUBLIC_FEED" | "MANUAL" | null {
  const normalized = value.toUpperCase();
  return normalized === "PUBLIC_API" ||
    normalized === "PUBLIC_FEED" ||
    normalized === "MANUAL"
    ? normalized
    : null;
}

export async function getMpiSummary(input: {
  tenantId: string;
  userId: string;
  subjectType: MpiSubjectType;
  subjectId?: string;
}): Promise<AiMpiSummaryResponse> {
  const storedReviews = await getReviewsForMpi(input);
  const reviews = storedReviews.flatMap((review) => {
    const collectionMethod = toCollectionMethod(review.collection_method);
    if (!collectionMethod) return [];
    return [
      {
        text: review.review_text,
        review_date: review.review_date.toISOString().slice(0, 10),
        collection_method: collectionMethod
      }
    ];
  });

  if (reviews.length === 0) {
    return {
      status: "UNKNOWN",
      evidence_id: null,
      sample_size: {
        status: "LOW_SAMPLE_SIZE",
        minimum_required: MINIMUM_REVIEW_COUNT
      }
    };
  }

  const response = await requestMarketIntelligence({
    reviews,
    subjectType: input.subjectType,
    subjectId: input.subjectId ?? null,
    countryCode: null,
    asOf: null
  });
  const result = response.mpi;
  const usableMpi = result.status === "OK" ? result.mpi : null;
  const isUsable = usableMpi !== null;
  const evidenceId = await persistMpiEvidence({
    tenantId: input.tenantId,
    userId: input.userId,
    subjectType: input.subjectType,
    subjectId: input.subjectId,
    status: isUsable ? "OK" : "UNKNOWN",
    mpi: usableMpi,
    reviewCount: result.review_count,
    weightedSentimentScore: result.weighted_sentiment_score,
    volumeConfidence: result.volume_confidence,
    explanationText: response.evidence_record.explanation_text,
    confidenceScore: response.evidence_record.confidence_score
  });

  const sampleStatus = isUsable ? "OK" : "LOW_SAMPLE_SIZE";
  const sampleSize = {
    status: sampleStatus,
    minimum_required: MINIMUM_REVIEW_COUNT
  } as const;

  if (usableMpi === null) {
    return { status: "UNKNOWN", evidence_id: evidenceId, sample_size: sampleSize };
  }

  return {
    status: "OK",
    evidence_id: evidenceId,
    mpi: usableMpi,
    sample_size: sampleSize,
    weighted_sentiment_score: result.weighted_sentiment_score,
    volume_confidence: result.volume_confidence,
    review_count: result.review_count,
    avg_recency_weight: result.avg_recency_weight,
    avg_reliability_weight: result.avg_reliability_weight,
    label_counts: result.label_counts
  };
}
