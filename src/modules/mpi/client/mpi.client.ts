import { z } from "zod";
import type {
  AiMpiSummaryResponse,
  MpiClientError,
  MpiSubjectType
} from "../types/mpi.types.js";

const DEFAULT_TIMEOUT_MS = 20_000;

const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const USE_AI_MOCKS = process.env.AI_SERVICE_USE_MOCKS === "true";

const labelCountsSchema = z.object({
  positive: z.number().int().nonnegative(),
  neutral: z.number().int().nonnegative(),
  negative: z.number().int().nonnegative()
});

const sampleSizeSchema = z.object({
  status: z.enum(["OK", "LOW_SAMPLE_SIZE"]),
  minimum_required: z.number().int().nonnegative()
});

const unknownSummarySchema = z.object({
  status: z.literal("UNKNOWN"),
  evidence_id: z.string().uuid()
});

const successSummarySchema = z.object({
  status: z.literal("OK"),
  evidence_id: z.string().uuid(),
  mpi: z.number().finite().min(0).max(100),
  sample_size: sampleSizeSchema,
  weighted_sentiment_score: z.number().finite().min(-1).max(1),
  volume_confidence: z.number().finite().min(0).max(1),
  review_count: z.number().int().nonnegative(),
  avg_recency_weight: z.number().finite(),
  avg_reliability_weight: z.number().finite(),
  label_counts: labelCountsSchema
});

const mpiSummaryResponseSchema = z.discriminatedUnion("status", [
  unknownSummarySchema,
  successSummarySchema
]);

const MOCK_MPI_SUMMARY_RESPONSE: AiMpiSummaryResponse = {
  status: "OK",
  evidence_id: "44444444-4444-4444-8444-444444444444",
  mpi: 72.4,
  sample_size: {
    status: "OK",
    minimum_required: 5
  },
  weighted_sentiment_score: 0.58,
  volume_confidence: 0.8,
  review_count: 18,
  avg_recency_weight: 0.91,
  avg_reliability_weight: 0.86,
  label_counts: {
    positive: 12,
    neutral: 4,
    negative: 2
  }
};

function createMpiClientError(
  message: string,
  upstreamStatus?: number
): MpiClientError {
  const error = new Error(message) as MpiClientError;
  error.name = "MpiClientError";
  error.upstreamStatus = upstreamStatus;
  return error;
}

export function isMpiClientError(error: unknown): error is MpiClientError {
  return error instanceof Error && error.name === "MpiClientError";
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
      throw createMpiClientError(
        `AI MPI service timed out after ${timeoutMs} ms.`
      );
    }

    throw createMpiClientError(
      error instanceof Error
        ? `AI MPI service request failed: ${error.message}`
        : "AI MPI service request failed."
    );
  } finally {
    clearTimeout(timeout);
  }
}

export async function requestMpiSummary(input: {
  subjectType: MpiSubjectType;
  subjectId?: string;
  authorization: string;
  timeoutMs?: number;
}): Promise<AiMpiSummaryResponse> {
  if (USE_AI_MOCKS) {
    return MOCK_MPI_SUMMARY_RESPONSE;
  }

  const url = new URL("mpi/summary", `${AI_SERVICE_URL}/`);
  url.searchParams.set("subject_type", input.subjectType);

  if (input.subjectId) {
    url.searchParams.set("subject_id", input.subjectId);
  }

  const response = await fetchWithTimeout(
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

  if (!response.ok) {
    throw createMpiClientError(
      `AI MPI service returned HTTP ${response.status}.`,
      response.status
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw createMpiClientError(
      "AI MPI service returned invalid JSON.",
      response.status
    );
  }

  const parsed = mpiSummaryResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createMpiClientError(
      "AI MPI service returned a summary response that does not match the CEOPRO AI API contract.",
      response.status
    );
  }

  return parsed.data;
}
