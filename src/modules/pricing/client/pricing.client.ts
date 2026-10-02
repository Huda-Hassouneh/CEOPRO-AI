import { z } from "zod";
import type {
  AiPricingResponse,
  PricingClientError
} from "../types/pricing.types.js";

const DEFAULT_TIMEOUT_MS = 20_000;

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const USE_AI_MOCKS = process.env.AI_SERVICE_USE_MOCKS === "true";

const MOCK_PRICING_RESPONSE: AiPricingResponse = {
  status: "OK",
  action: "lower",
  current_price: 120,
  suggested_price: 112.5,
  guardrail_clamped: false,
  margin_guardrail_clamped: false,
  matched_competitor_count: 4,
  confidence_score: 0.65,
  evidence_id: "11111111-1111-4111-8111-111111111111",
  outcome_id: "22222222-2222-4222-8222-222222222222"
};

const unknownResponseSchema = z.object({
  status: z.literal("UNKNOWN"),
  evidence_id: z.string().uuid()
});

const successResponseSchema = z.object({
  status: z.literal("OK"),
  action: z.enum(["raise", "lower", "hold"]),
  current_price: z.number().finite().nonnegative(),
  suggested_price: z.number().finite().nonnegative(),
  guardrail_clamped: z.boolean(),
  margin_guardrail_clamped: z.boolean().nullable(),
  matched_competitor_count: z.number().int().nonnegative(),
  confidence_score: z.number().min(0.25).max(0.75),
  evidence_id: z.string().uuid(),
  outcome_id: z.string().uuid()
});

const pricingResponseSchema = z.discriminatedUnion("status", [
  unknownResponseSchema,
  successResponseSchema
]);

function createPricingClientError(
  message: string,
  upstreamStatus?: number
): PricingClientError {
  const error = new Error(message) as PricingClientError;

  error.name = "PricingClientError";
  error.upstreamStatus = upstreamStatus;

  return error;
}

export function isPricingClientError(
  error: unknown
): error is PricingClientError {
  return error instanceof Error && error.name === "PricingClientError";
}

async function fetchWithTimeout(
  input: string | URL,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();

  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw createPricingClientError(
        `AI pricing service timed out after ${timeoutMs} ms.`
      );
    }

    throw createPricingClientError(
      error instanceof Error
        ? `AI pricing service request failed: ${error.message}`
        : "AI pricing service request failed."
    );
  } finally {
    clearTimeout(timeout);
  }
}

export async function requestPricingRecommendation(input: {
  productId: string;
  authorization: string;
  timeoutMs?: number;
}): Promise<AiPricingResponse> {
  if (USE_AI_MOCKS) {
    return MOCK_PRICING_RESPONSE;
  }

  const url = new URL("pricing/recommend", `${AI_SERVICE_URL}/`);

  url.searchParams.set("product_id", input.productId);

  const response = await fetchWithTimeout(
    url,
    {
      method: "POST",
      headers: {
        Authorization: input.authorization,
        Accept: "application/json"
      }
    },
    input.timeoutMs ?? DEFAULT_TIMEOUT_MS
  );

  if (!response.ok) {
    throw createPricingClientError(
      `AI pricing service returned HTTP ${response.status}.`,
      response.status
    );
  }

  let payload: unknown;

  try {
    payload = await response.json();
  } catch {
    throw createPricingClientError(
      "AI pricing service returned invalid JSON.",
      response.status
    );
  }

  const parsed = pricingResponseSchema.safeParse(payload);

  if (!parsed.success) {
    throw createPricingClientError(
      "AI pricing service returned a response that does not match the CEOPRO AI API contract.",
      response.status
    );
  }

  return parsed.data;
}
