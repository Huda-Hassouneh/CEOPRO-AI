import { getGradioRuntimeConfig } from "./config.js";
import {
  createAiIntegrationError,
  type AiServiceName,
  type GradioClient,
  type GradioRuntimeConfig
} from "./ai.types.js";
import { readGradioSseResult } from "./sse.js";

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit
) => Promise<Response>;

type CachedToken = {
  value: string;
  expiresAt: number;
};

type EncryptedToken = {
  encrypted: string;
  keyId: string;
};

export type GradioClientOptions = {
  getConfig?: (service: AiServiceName) => GradioRuntimeConfig;
  fetchImpl?: FetchLike;
  now?: () => number;
  refreshSkewMs?: number;
};

const EVENT_ID_PATTERN = /^[A-Za-z0-9_-]{1,256}$/;

async function fetchWithTimeout(
  fetchImpl: FetchLike,
  input: string | URL,
  init: RequestInit,
  timeoutMs: number,
  serviceName: string
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetchImpl(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      throw createAiIntegrationError(
        `${serviceName} request timed out after ${timeoutMs} ms.`,
        "timeout"
      );
    }
    throw createAiIntegrationError(`${serviceName} request failed.`, "network");
  } finally {
    clearTimeout(timeout);
  }
}

function responseError(serviceName: string, response: Response) {
  return createAiIntegrationError(
    `${serviceName} returned HTTP ${response.status}.`,
    "upstream_http",
    response.status
  );
}

async function readJson(response: Response, label: string): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw createAiIntegrationError(
      `${label} returned invalid JSON.`,
      "malformed_response",
      response.status
    );
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getEncryptedTokenHeaderValue(payload: unknown): string | null {
  if (!isRecord(payload)) return null;

  const token = payload.encryptedToken;
  if (typeof token === "string" && token.trim()) return token;
  if (
    isRecord(token) &&
    typeof token.encrypted === "string" &&
    token.encrypted.trim() &&
    typeof token.keyId === "string" &&
    token.keyId.trim()
  ) {
    // The Hub currently returns an envelope containing both the ciphertext
    // and the key id. Preserve both when placing it in the ZeroGPU header.
    const encryptedToken: EncryptedToken = {
      encrypted: token.encrypted,
      keyId: token.keyId
    };
    return JSON.stringify(encryptedToken);
  }
  return null;
}

export function createGradioClient(
  options: GradioClientOptions = {}
): GradioClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? Date.now;
  const refreshSkewMs = options.refreshSkewMs ?? 90_000;
  const getConfig = options.getConfig ?? getGradioRuntimeConfig;
  const cache = new Map<AiServiceName, CachedToken>();
  const pendingTokens = new Map<AiServiceName, Promise<CachedToken>>();

  const acquireToken = async (
    service: AiServiceName,
    forceRefresh = false
  ): Promise<CachedToken> => {
    const config = getConfig(service);
    const cached = cache.get(service);
    if (!forceRefresh && cached && cached.expiresAt - refreshSkewMs > now()) {
      return cached;
    }

    const pending = pendingTokens.get(service);
    if (pending) return pending;

    const tokenPromise = (async () => {
      const url = new URL(
        `/api/spaces/${encodeURIComponent(config.service.spaceId).replace(/%2F/gi, "/")}/jwt`,
        config.huggingFaceApiUrl
      );
      url.searchParams.set(
        "expiration",
        new Date(now() + config.tokenExpiresInSeconds * 1000).toISOString()
      );
      url.searchParams.set("billing_details", "true");
      url.searchParams.set("encrypted", "true");

      const response = await fetchWithTimeout(
        fetchImpl,
        url,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${config.huggingFaceAccessToken}`,
            Accept: "application/json"
          }
        },
        config.timeoutMs,
        "Hugging Face ZeroGPU authentication"
      );

      if (!response.ok) {
        throw responseError("Hugging Face ZeroGPU authentication", response);
      }

      const payload = await readJson(
        response,
        "Hugging Face ZeroGPU authentication"
      );
      const tokenValue = getEncryptedTokenHeaderValue(payload);
      if (!tokenValue) {
        throw createAiIntegrationError(
          "Hugging Face returned an unsupported encrypted ZeroGPU token response.",
          "malformed_response",
          response.status
        );
      }

      const entry = {
        value: tokenValue,
        expiresAt: now() + config.tokenExpiresInSeconds * 1000
      };
      cache.set(service, entry);
      return entry;
    })();

    pendingTokens.set(service, tokenPromise);
    try {
      return await tokenPromise;
    } finally {
      if (pendingTokens.get(service) === tokenPromise) {
        pendingTokens.delete(service);
      }
    }
  };

  const authorizedFetch = async (
    service: AiServiceName,
    input: string | URL,
    init: RequestInit,
    timeoutMs: number,
    serviceName: string
  ): Promise<Response> => {
    let token = await acquireToken(service);
    const send = (tokenValue: string) =>
      fetchWithTimeout(
        fetchImpl,
        input,
        {
          ...init,
          headers: {
            ...(init.headers as Record<string, string> | undefined),
            "X-ZeroGPU-Token": tokenValue
          }
        },
        timeoutMs,
        serviceName
      );

    let response = await send(token.value);
    if (response.status === 401) {
      cache.delete(service);
      token = await acquireToken(service, true);
      response = await send(token.value);
    }
    return response;
  };

  return {
    call: async ({ service, apiName, data, timeoutMs }): Promise<unknown> => {
      if (!/^[A-Za-z0-9_-]{1,100}$/.test(apiName)) {
        throw createAiIntegrationError(
          "Invalid Gradio API name.",
          "configuration"
        );
      }

      const config = getConfig(service);
      const requestTimeout = timeoutMs ?? config.timeoutMs;
      const apiUrl = `${config.service.baseUrl}/gradio_api/call/${apiName}`;
      const postResponse = await authorizedFetch(
        service,
        apiUrl,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json"
          },
          body: JSON.stringify({ data })
        },
        requestTimeout,
        "Gradio job submission"
      );

      if (!postResponse.ok) {
        throw responseError("Gradio job submission", postResponse);
      }

      const postPayload = await readJson(postResponse, "Gradio job submission");
      const eventId = isRecord(postPayload) ? postPayload.event_id : undefined;
      if (typeof eventId !== "string" || !EVENT_ID_PATTERN.test(eventId)) {
        throw createAiIntegrationError(
          "Gradio job submission returned an invalid event_id.",
          "malformed_response",
          postResponse.status
        );
      }

      const resultResponse = await authorizedFetch(
        service,
        `${apiUrl}/${encodeURIComponent(eventId)}`,
        {
          method: "GET",
          headers: { Accept: "text/event-stream" }
        },
        requestTimeout,
        "Gradio result retrieval"
      );

      if (!resultResponse.ok) {
        throw responseError("Gradio result retrieval", resultResponse);
      }

      const contentType = resultResponse.headers.get("content-type") ?? "";
      if (!contentType.toLowerCase().includes("text/event-stream")) {
        throw createAiIntegrationError(
          "Gradio result retrieval did not return an SSE stream.",
          "malformed_response",
          resultResponse.status
        );
      }
      if (!resultResponse.body) {
        throw createAiIntegrationError(
          "Gradio result retrieval returned an empty stream.",
          "malformed_response",
          resultResponse.status
        );
      }

      try {
        return await readGradioSseResult(resultResponse.body, requestTimeout);
      } catch (error) {
        if (error instanceof Error && error.name === "AiIntegrationError") {
          throw error;
        }
        throw createAiIntegrationError(
          "Gradio result retrieval failed while parsing SSE.",
          "malformed_response",
          resultResponse.status
        );
      }
    }
  };
}

export const gradioClient = createGradioClient();
