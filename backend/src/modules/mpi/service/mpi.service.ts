import { requestMarketIntelligence } from "../client/mpi.client.js";
import { getReviewsForMpi, persistMpiEvidence } from "../repo/mpi.repo.js";
import { getFeatureAccessInfo } from "../../features/repo/usage.repo.js";
import { eligibleMpiReviews, MPI_SAMPLE_LIMIT, MpiAccessError, mpiSampleDecision, validateMpiSubject } from "./mpi.policy.js";
import type { AiMpiSummaryResponse, MpiEvidence, MpiReason, MpiSubjectType } from "../types/mpi.types.js";

export async function getMpiSummary(input: {
  tenantId: string; userId: string; subjectType: MpiSubjectType; subjectId?: string;
}): Promise<AiMpiSummaryResponse> {
  validateMpiSubject(input);
  const { subscription, planFeature } = await getFeatureAccessInfo(input.tenantId, "market_perception");
  if (!subscription) throw new MpiAccessError("SUBSCRIPTION_NOT_FOUND");
  if (!planFeature) throw new MpiAccessError("FEATURE_NOT_INCLUDED");

  const asOf = new Date();
  const scope = await getReviewsForMpi({ ...input, asOf });
  const eligible = eligibleMpiReviews(scope.reviews, asOf);
  const subjectId = input.subjectType === "BUSINESS" ? input.tenantId : input.subjectId!;
  const dates = eligible.map((review) => review.review_date.toISOString()).sort();
  const evidence: MpiEvidence = {
    explanation: null,
    source_review_ids: eligible.map((review) => review.review_id),
    source_scope: "submitted_sample",
    observation_period: { start: dates[0] ?? null, end: dates[dates.length - 1] ?? null },
    collection_methods: [...new Set(eligible.map((review) => review.collection_method))].sort(),
    eligible_review_count: eligible.length,
    sample_limit: MPI_SAMPLE_LIMIT,
    sentiment_model: null,
    model_revision: null
  };
  const context = {
    subject_type: input.subjectType, subject_id: subjectId, as_of: asOf.toISOString(),
    review_count: eligible.length, confidence_score: null, evidence
  };
  const localSample = mpiSampleDecision(eligible.length, eligible.length);
  if (localSample.status === "LOW_SAMPLE_SIZE") {
    return {
      ...context, status: "UNKNOWN", evidence_id: null, label_counts: null,
      reason: eligible.length === 0 ? "NO_ELIGIBLE_REVIEWS" : "INSUFFICIENT_REVIEWS",
      sample_size: localSample, analysis_performed: false
    };
  }

  const response = await requestMarketIntelligence({
    reviews: eligible.map((review) => ({
      text: review.review_text.trim(), review_date: review.review_date.toISOString().slice(0, 10),
      collection_method: review.collection_method as "PUBLIC_API" | "PUBLIC_FEED" | "MANUAL"
    })),
    subjectType: input.subjectType,
    subjectId: input.subjectType === "BUSINESS" ? null : subjectId,
    // Country of the company is not the country of each review.
    countryCode: null,
    asOf: asOf.toISOString().slice(0, 10)
  });
  const result = response.mpi;
  const sampleSize = mpiSampleDecision(result.sample_size, result.review_count);
  const reason: MpiReason | null = result.review_count === 0
    ? "MODEL_UNAVAILABLE"
    : sampleSize.status === "LOW_SAMPLE_SIZE" || result.status === "LOW_SAMPLE_SIZE"
      ? "INSUFFICIENT_REVIEWS"
      : result.status !== "OK" || sampleSize.status === "UNKNOWN" || result.mpi === null
        ? "MODEL_UNAVAILABLE" : null;
  if (reason === "INSUFFICIENT_REVIEWS") sampleSize.status = "LOW_SAMPLE_SIZE";
  const status = reason === null ? "OK" : "UNKNOWN";
  evidence.explanation = response.evidence_record.explanation_text;
  evidence.sentiment_model = response.sentiment_model;
  evidence.model_revision = response.sentiment_model_revision;
  const confidence = response.evidence_record.confidence_score;
  const evidenceId = await persistMpiEvidence({
    tenantId: input.tenantId, userId: input.userId, subjectType: input.subjectType, subjectId,
    status, reason, mpi: status === "OK" ? result.mpi : null,
    reviewCount: result.review_count, weightedSentimentScore: result.weighted_sentiment_score,
    volumeConfidence: result.volume_confidence, explanationText: evidence.explanation,
    confidenceScore: confidence, evidence, asOf: context.as_of,
    sampleSize, labelCounts: result.label_counts
  });
  const enrichedContext = {
    ...context, review_count: result.review_count, confidence_score: confidence,
    analysis_performed: true, evidence_id: evidenceId, evidence, sample_size: sampleSize
  };
  if (status !== "OK") {
    return { ...enrichedContext, status: "UNKNOWN", reason: reason!, label_counts: result.label_counts };
  }
  return {
    ...enrichedContext, status: "OK", reason: null, mpi: result.mpi!,
    weighted_sentiment_score: result.weighted_sentiment_score,
    volume_confidence: result.volume_confidence,
    avg_recency_weight: result.avg_recency_weight,
    avg_reliability_weight: result.avg_reliability_weight,
    label_counts: result.label_counts
  };
}
