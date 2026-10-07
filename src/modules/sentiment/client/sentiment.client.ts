import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";

const sentimentResponseSchema = z.object({
  model: z.string(),
  model_revision: z.string(),
  results: z.array(
    z.object({
      text: z.string(),
      label: z.enum(["positive", "neutral", "negative"]),
      positive_probability: z.number().finite().min(0).max(1),
      neutral_probability: z.number().finite().min(0).max(1),
      negative_probability: z.number().finite().min(0).max(1),
      confidence: z.number().finite().min(0).max(1),
      model_version: z.string()
    })
  )
});

export type SentimentGradioResponse = z.infer<typeof sentimentResponseSchema>;
export { isAiIntegrationError as isSentimentClientError };

export async function requestSentimentClassification(
  texts: string[],
  client: GradioClient = gradioClient
): Promise<SentimentGradioResponse> {
  if (texts.length < 1 || texts.length > 64 || texts.some((text) => !text.trim())) {
    throw createAiIntegrationError(
      "Sentiment requests require 1 to 64 non-empty texts.",
      "configuration"
    );
  }

  const payload = await client.call({
    service: "models",
    apiName: "sentiment",
    data: [texts],
    timeoutMs: 60_000
  });
  const parsed = sentimentResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createAiIntegrationError(
      "Gradio sentiment response did not match the documented output schema.",
      "malformed_response"
    );
  }
  if (parsed.data.results.length !== texts.length) {
    throw createAiIntegrationError(
      "Gradio sentiment response count did not match the submitted texts.",
      "malformed_response"
    );
  }
  return parsed.data;
}
