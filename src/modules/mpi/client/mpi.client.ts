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
      label: z.enum(["positive", "neutral", "negative"]),
      sentiment_score: z.number().finite(),
      confidence: z.number().finite().min(0).max(1)
    })
  ),
  mpi: z.object({
    status: z.enum(["OK", "LOW_SAMPLE_SIZE", "UNKNOWN"]),
    mpi: z.number().finite().min(0).max(100).nullable(),
    sample_size: z.unknown(),
    weighted_sentiment_score: z.number().finite().min(-1).max(1),
    volume_confidence: z.number().finite().min(0).max(1),
    review_count: z.number().int().nonnegative(),
    avg_recency_weight: z.number().finite(),
    avg_reliability_weight: z.number().finite(),
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
  return parsed.data;
}
