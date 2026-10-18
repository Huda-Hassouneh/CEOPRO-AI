import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";
import type { AiPricingRequest, AiPricingResult } from "../types/pricing.types.js";

const unknownResultSchema = z.object({ status: z.literal("UNKNOWN") }).passthrough();

const successResultSchema = z
  .object({
    status: z.literal("OK"),
    action: z.enum(["raise", "lower", "hold"]),
    current_price: z.number().finite().nonnegative(),
    suggested_price: z.number().finite().nonnegative(),
    guardrail_clamped: z.boolean(),
    margin_guardrail_clamped: z.boolean().nullable(),
    matched_competitor_count: z.number().int().nonnegative(),
    confidence_score: z.number().finite().min(0).max(1)
  })
  .passthrough();

export const pricingGradioResponseSchema = z.object({
  result: z.discriminatedUnion("status", [
    unknownResultSchema,
    successResultSchema
  ]),
  persisted_records: z.array(z.unknown())
});

export type PricingGradioResponse = z.infer<typeof pricingGradioResponseSchema>;
export { isAiIntegrationError as isPricingClientError };

export function buildPricingGradioData(input: AiPricingRequest): unknown[] {
  return [
    {
      product_name: input.product.product_name,
      current_price: input.product.current_price,
      currency: input.product.currency,
      cost_price: input.product.cost_price
    },
    input.competitorPrices.map((price) => ({
      competitor_name: price.competitor_name,
      price: price.price,
      currency: price.currency,
      observed_at: price.observed_at
    })),
    input.exchangeRates
  ];
}

export async function requestPricingRecommendation(
  input: AiPricingRequest,
  client: GradioClient = gradioClient
): Promise<PricingGradioResponse> {
  const payload = await client.call({
    service: "analytics",
    apiName: "recommend",
    data: buildPricingGradioData(input)
  });
  const parsed = pricingGradioResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createAiIntegrationError(
      "Gradio pricing response did not match the documented output schema.",
      "malformed_response"
    );
  }
  return parsed.data;
}

export function toAiPricingResult(response: PricingGradioResponse): AiPricingResult {
  return response.result;
}

export function readPricingExplanation(
  response: PricingGradioResponse
): string | null {
  for (const record of response.persisted_records) {
    if (
      typeof record === "object" &&
      record !== null &&
      !Array.isArray(record) &&
      typeof (record as Record<string, unknown>).explanation_text === "string"
    ) {
      return (record as Record<string, unknown>).explanation_text as string;
    }
  }
  return null;
}
