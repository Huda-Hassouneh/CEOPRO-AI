import { randomUUID } from "node:crypto";
// import type { JsonObject } from "../t";
import { safeUploadName } from "../validators/pricing.validation.js";
import { JsonObject } from "../../dataconnection/types/dataconnection.types.js";

const TESTING_MODE = true;
const AI_SERVICE_URL = (
  process.env.AI_SERVICE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const LONG_TIMEOUT_MS = 60_000;

export type AiServiceError = Error & {
  name: "AiServiceError";
  upstreamStatus?: number;
};

export function createAiServiceError(
  message: string,
  upstreamStatus?: number
): AiServiceError {
  const error = new Error(message) as AiServiceError;

  error.name = "AiServiceError";
  error.upstreamStatus = upstreamStatus;

  return error;
}

export function isAiServiceError(error: unknown): error is AiServiceError {
  return error instanceof Error && error.name === "AiServiceError";
}

function aiUrl(pathname: string): URL {
  return new URL(pathname, `${AI_SERVICE_URL}/`);
}

function mockExtractionData(tenantId: string, fileName: string): JsonObject {
  return {
    job_id: randomUUID(),
    template_mode: "best-effort mapping",
    is_template_compliant: false,

    rows_processed: 150,
    rows_partial: 12,
    rows_failed: 3,

    data_loss_pct: 2.0,
    header_coverage_ratio: 0.88,

    minio_object_key: `raw-uploads/tenant-${tenantId?.substring(0, 8)}/${fileName}`,

    row_outcomes: [],

    promotion: {
      rows_promoted: 135,
      rows_skipped_incomplete: 12,
      rows_failed: 3,
      products_created: 18,
      errors: []
    },

    currency_resolution: {
      currency: "USD",
      needs_confirmation: true
    }
  };
}

function mockProcessPendingData(limit: number): JsonObject {
  return {
    news_processed: Math.min(limit, 10),
    social_mentions_processed: Math.min(limit, 10)
  };
}

async function parseJsonResponse(response: Response): Promise<JsonObject> {
  try {
    const data = await response.json();

    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("Response body must be a JSON object.");
    }

    return data as JsonObject;
  } catch {
    throw createAiServiceError(
      "AI service returned an invalid JSON response.",
      response.status
    );
  }
}

async function requestJson(
  url: URL,
  init: RequestInit,
  timeoutMs = LONG_TIMEOUT_MS
): Promise<JsonObject> {
  const controller = new AbortController();

  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal
    });

    if (!response.ok) {
      throw createAiServiceError(
        `AI extraction service returned HTTP ${response.status}.`,
        response.status
      );
    }

    return await parseJsonResponse(response);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw createAiServiceError(
        `AI extraction service request timed out after ${timeoutMs} ms.`
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function uploadExtractionFile(args: {
  tenantId: string;

  file: {
    originalname: string;
    mimetype: string;
    buffer: Buffer;
  };

  authorization?: string;
}): Promise<JsonObject> {
  const fileName = safeUploadName(args.file.originalname);

  // Replace TESTING_MODE with your existing
  // project's actual global variable.
  if (TESTING_MODE) {
    return mockExtractionData(args.tenantId, fileName);
  }

  const formData = new FormData();

  formData.append(
    "file",
    new Blob([new Uint8Array(args.file.buffer)], {
      type: args.file.mimetype
    }),
    fileName
  );

  return requestJson(aiUrl("extraction/upload"), {
    method: "POST",

    headers: args.authorization
      ? {
          Authorization: args.authorization
        }
      : {},

    body: formData
  });
}

export async function processPendingExtraction(args: {
  limit: number;
  authorization?: string;
}): Promise<JsonObject> {
  if (TESTING_MODE) {
    return mockProcessPendingData(args.limit);
  }

  const url = aiUrl("extraction/process-pending");

  url.searchParams.set("limit", String(args.limit));

  return requestJson(url, {
    method: "POST",

    headers: args.authorization
      ? {
          Authorization: args.authorization
        }
      : {}
  });
}
