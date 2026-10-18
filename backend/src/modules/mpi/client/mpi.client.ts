import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";
import type { MpiSubjectType } from "../types/mpi.types.js";

const marketIntelligenceResponseSchema = z.object({
  sentiment_model: z.string(),
  sentiment_model_revision: z.string(),
  classification: z.unknown(),
  reviews: z.array(
    z.object({
      review_id: z.unknown(),
      text: z.string(),
      label: z.enum(["positive", "neutral", "negative", "POSITIVE", "NEUTRAL", "NEGATIVE"])
        .transform((label) => label.toLowerCase() as "positive" | "neutral" | "negative"),
      sentiment_score: z.number().finite().min(-1).max(1),
      confidence: z.number().finite().min(0).max(1)
    })
  ),
  mpi: z.object({
    status: z.enum(["OK", "LOW_SAMPLE_SIZE", "UNKNOWN"]),
    mpi: z.number().finite().min(0).max(100).nullable(),
    sample_size: z.union([
      z.number().int().nonnegative(),
      z.object({
        status: z.enum(["OK", "LOW_SAMPLE_SIZE", "UNKNOWN"]),
        minimum_required: z.number().int().positive().optional(),
        review_count: z.number().int().nonnegative().optional(),
        analyzed_count: z.number().int().nonnegative().optional(),
        sufficient: z.boolean().optional()
      })
    ]),
    weighted_sentiment_score: z.number().finite().min(-1).max(1),
    volume_confidence: z.number().finite().min(0).max(1),
    review_count: z.number().int().nonnegative(),
    avg_recency_weight: z.number().finite().min(0).max(1),
    avg_reliability_weight: z.number().finite().min(0).max(1),
    label_counts: z.object({
      positive: z.number().int().nonnegative(),
      neutral: z.number().int().nonnegative(),
      negative: z.number().int().nonnegative()
    })
  }),
  evidence_record: z.object({
    explanation_text: z.string(),
    confidence_score: z.number().finite().min(0).max(1)
  })
});

export type MarketIntelligenceGradioResponse = z.infer<
  typeof marketIntelligenceResponseSchema
>;
export { isAiIntegrationError as isMpiClientError };

export type MpiReviewInput = {
  text: string;
  review_date: string;
  collection_method: "PUBLIC_API" | "PUBLIC_FEED" | "MANUAL";
};

export function buildMarketIntelligenceData(input: {
  reviews: MpiReviewInput[];
  subjectType: MpiSubjectType;
  subjectId?: string | null;
  countryCode?: string | null;
  asOf?: string | null;
}): unknown[] {
  return [
    input.reviews,
    input.subjectType,
    input.subjectId ?? null,
    input.countryCode ?? null,
    input.asOf ?? null
  ];
}

export async function requestMarketIntelligence(
  input: {
    reviews: MpiReviewInput[];
    subjectType: MpiSubjectType;
    subjectId?: string | null;
    countryCode?: string | null;
    asOf?: string | null;
  },
  client: GradioClient = gradioClient
): Promise<MarketIntelligenceGradioResponse> {
  const payload = await client.call({
    service: "models",
    apiName: "market_intelligence",
    data: buildMarketIntelligenceData(input)
  });
  const parsed = marketIntelligenceResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createAiIntegrationError(
      "Gradio market-intelligence response did not match the documented output schema.",
      "malformed_response"
    );
  }
  const result = parsed.data.mpi;
  const labels = result.label_counts;
  const analyzedLabels = { positive: 0, neutral: 0, negative: 0 };
  const submittedTexts = new Map<string, number>();
  for (const review of input.reviews) submittedTexts.set(review.text.trim(), (submittedTexts.get(review.text.trim()) ?? 0) + 1);
  for (const review of parsed.data.reviews) {
    const text = review.text.trim();
    const remaining = submittedTexts.get(text) ?? 0;
    if (!remaining) throw createAiIntegrationError("MPI response contained a review outside the submitted sample.", "malformed_response");
    submittedTexts.set(text, remaining - 1);
    analyzedLabels[review.label] += 1;
  }
  const sampleCounts = typeof result.sample_size === "number"
    ? [result.sample_size]
    : [result.sample_size.review_count, result.sample_size.analyzed_count];
  if (result.review_count > input.reviews.length ||
      result.review_count !== parsed.data.reviews.length ||
      labels.positive + labels.neutral + labels.negative !== result.review_count ||
      Object.keys(analyzedLabels).some((key) => analyzedLabels[key as keyof typeof labels] !== labels[key as keyof typeof labels]) ||
      sampleCounts.some((count) => count !== undefined && count !== result.review_count) ||
      (result.status === "OK" && result.mpi === null)) {
    throw createAiIntegrationError("MPI response counts or result contradicted its analyzed sample.", "malformed_response");
  }
  return parsed.data;
}
