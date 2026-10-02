import { z } from "zod";
import type {
  AiSentimentAnalyzePendingResponse,
  AiSentimentSummaryResponse,
  SentimentClientError,
  SentimentSubjectType
} from "../types/sentiment.types.js";

const DEFAULT_TIMEOUT_MS = 20_000;
const ANALYZE_TIMEOUT_MS = 60_000;

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const USE_AI_MOCKS = process.env.AI_SERVICE_USE_MOCKS === "true";

const sampleSizeSchema = z.object({
  status: z.enum(["OK", "LOW_SAMPLE_SIZE"]),
  minimum_required: z.number().int().nonnegative()
});

const unknownSummarySchema = z.object({
  status: z.literal("UNKNOWN"),
  evidence_id: z.string().uuid(),
  sample_size: z.object({
    status: z.literal("LOW_SAMPLE_SIZE"),
    minimum_required: z.number().int().nonnegative()
  })
});

const successSummarySchema = z.object({
  status: z.literal("OK"),
  evidence_id: z.string().uuid(),
  sentiment_score: z.number().min(-1).max(1),
  label_counts: z.object({
    positive: z.number().int().nonnegative(),
    neutral: z.number().int().nonnegative(),
    negative: z.number().int().nonnegative()
  }),
  sample_size: sampleSizeSchema
});

const summaryResponseSchema = z.discriminatedUnion("status", [
  unknownSummarySchema,
  successSummarySchema
]);

const analyzePendingResponseSchema = z.object({
  status: z.literal("OK"),
  analyzed_count: z.number().int().nonnegative()
});

const MOCK_SUMMARY_RESPONSE: AiSentimentSummaryResponse = {
  status: "OK",
  evidence_id: "33333333-3333-4333-8333-333333333333",
  sentiment_score: 0.62,
  label_counts: {
    positive: 12,
    neutral: 18,
    negative: 2
  },
  sample_size: {
    status: "OK",
    minimum_required: 5
  }
};

function createSentimentClientError(
  message: string,
  upstreamStatus?: number
): SentimentClientError {
  const error = new Error(message) as SentimentClientError;
  error.name = "SentimentClientError";
  error.upstreamStatus = upstreamStatus;
  return error;
}

export function isSentimentClientError(
  error: unknown
): error is SentimentClientError {
  return error instanceof Error && error.name === "SentimentClientError";
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
      throw createSentimentClientError(
        `AI sentiment service timed out after ${timeoutMs} ms.`
      );
    }

    throw createSentimentClientError(
      error instanceof Error
        ? `AI sentiment service request failed: ${error.message}`
        : "AI sentiment service request failed."
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function requestJson(
  url: URL,
  init: RequestInit,
  timeoutMs: number
): Promise<unknown> {
  const response = await fetchWithTimeout(url, init, timeoutMs);

  if (!response.ok) {
    throw createSentimentClientError(
      `AI sentiment service returned HTTP ${response.status}.`,
      response.status
    );
  }

  try {
    return await response.json();
  } catch {
    throw createSentimentClientError(
      "AI sentiment service returned invalid JSON.",
      response.status
    );
  }
}

export async function requestSentimentSummary(input: {
  subjectType: SentimentSubjectType;
  subjectId?: string;
  countryContext?: string;
  authorization: string;
  timeoutMs?: number;
}): Promise<AiSentimentSummaryResponse> {
  if (USE_AI_MOCKS) {
    return MOCK_SUMMARY_RESPONSE;
  }

  const url = new URL("sentiment/summary", `${AI_SERVICE_URL}/`);
  url.searchParams.set("subject_type", input.subjectType);

  if (input.subjectId) {
    url.searchParams.set("subject_id", input.subjectId);
  }

  if (input.countryContext) {
    url.searchParams.set("country_context", input.countryContext);
  }

  const payload = await requestJson(
    url,
    {
      method: "GET",
      headers: {
        Authorization: input.authorization,
        Accept: "application/json"
      }
    },
    input.timeoutMs ?? DEFAULT_TIMEOUT_MS
  );

  const parsed = summaryResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createSentimentClientError(
      "AI sentiment service returned a summary response that does not match the CEOPRO AI API contract."
    );
  }

  return parsed.data;
}

export async function requestAnalyzePendingSentiment(input: {
  batchSize: number;
  authorization: string;
  timeoutMs?: number;
}): Promise<AiSentimentAnalyzePendingResponse> {
  if (USE_AI_MOCKS) {
    return {
      status: "OK",
      analyzed_count: Math.min(input.batchSize, 5)
    };
  }

  const url = new URL("sentiment/analyze-pending", `${AI_SERVICE_URL}/`);
  url.searchParams.set("batch_size", String(input.batchSize));

  const payload = await requestJson(
    url,
    {
      method: "POST",
      headers: {
        Authorization: input.authorization,
        Accept: "application/json"
      }
    },
    input.timeoutMs ?? ANALYZE_TIMEOUT_MS
  );

  const parsed = analyzePendingResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createSentimentClientError(
      "AI sentiment service returned an analyze-pending response that does not match the CEOPRO AI API contract."
    );
  }

  return parsed.data;
}
