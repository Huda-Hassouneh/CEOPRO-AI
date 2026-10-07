import assert from "node:assert/strict";
import test from "node:test";
import type { GradioRuntimeConfig } from "../../src/integrations/ai/ai.types.js";
import { ERROR_CODES } from "../../src/errors/error-codes.js";
import { getGradioRuntimeConfig } from "../../src/integrations/ai/config.js";
import {
  createGradioClient,
  type GradioClientOptions
} from "../../src/integrations/ai/gradio.client.js";
import { readGradioSseResult } from "../../src/integrations/ai/sse.js";
import { sendApiError } from "../../src/utils/http.js";

const baseConfig: GradioRuntimeConfig = {
  huggingFaceAccessToken: "hf-secret-value",
  service: {
    spaceId: "team/ceopro-models",
    baseUrl: "https://ceopro-models.hf.space"
  },
  huggingFaceApiUrl: "https://huggingface.co",
  tokenExpiresInSeconds: 3600,
  timeoutMs: 1000
};

const configFor = () => ({ ...baseConfig, service: { ...baseConfig.service } });
const completeResponse = (payload: unknown = { ok: true }) =>
  new Response(`event: complete\ndata: ${JSON.stringify([payload])}\n\n`, {
    headers: { "content-type": "text/event-stream" }
  });

function mockFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response> | Response
): NonNullable<GradioClientOptions["fetchImpl"]> {
  return (async (input, init) => handler(String(input), init)) as NonNullable<
    GradioClientOptions["fetchImpl"]
  >;
}

function isTokenUrl(url: string): boolean {
  return url.includes("/api/spaces/team/ceopro-models/jwt");
}

test("SSE parser accepts split UTF-8 frames and returns the one completion value", async () => {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('event: complete\ndata: [{"answer":"'));
      controller.enqueue(encoder.encode('ok"}]\n\n'));
      controller.close();
    }
  });

  assert.deepEqual(await readGradioSseResult(stream), { answer: "ok" });
});

test("SSE parser turns error, malformed completion and timeout into typed errors", async () => {
  await assert.rejects(
    readGradioSseResult(
      new Response("event: error\ndata: failed\n\n").body!
    ),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "upstream_event"
  );
  await assert.rejects(
    readGradioSseResult(
      new Response("event: complete\ndata: {bad json}\n\n").body!
    ),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "malformed_response"
  );
  await assert.rejects(
    readGradioSseResult(new ReadableStream<Uint8Array>({ start() {} }), 10),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "timeout"
  );
});

test("shared client acquires one ZeroGPU token and sends it on both Gradio calls", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let tokenRequests = 0;
  const client = createGradioClient({
    getConfig: configFor,
    fetchImpl: mockFetch((url, init) => {
      calls.push({ url, init });
      if (isTokenUrl(url)) {
        tokenRequests += 1;
        assert.equal(
          new Headers(init?.headers).get("authorization"),
          "Bearer hf-secret-value"
        );
        return Response.json({
          encryptedToken: { encrypted: "zero-token-1", keyId: "hf-key-1" }
        });
      }
      if (init?.method === "POST") {
        return Response.json({ event_id: "job_123" });
      }
      return completeResponse({ answer: 42 });
    })
  });

  assert.deepEqual(
    await client.call({ service: "models", apiName: "rag_answer", data: [1, null] }),
    { answer: 42 }
  );
  await client.call({ service: "models", apiName: "rag_answer", data: [2] });
  assert.equal(tokenRequests, 1);

  const gradioCalls = calls.filter((call) => !isTokenUrl(call.url));
  const tokenRequest = calls.find((call) => isTokenUrl(call.url));
  const tokenUrl = new URL(tokenRequest!.url);
  assert.ok(tokenUrl.searchParams.has("expiration"));
  assert.equal(tokenUrl.searchParams.has("expires_in"), false);
  assert.equal(tokenUrl.searchParams.get("encrypted"), "true");
  assert.equal(gradioCalls.length, 4);
  const firstSubmission = gradioCalls.find((call) => call.init?.method === "POST");
  assert.deepEqual(JSON.parse(String(firstSubmission?.init?.body)), {
    data: [1, null]
  });
  for (const call of gradioCalls) {
    assert.equal(
      new Headers(call.init?.headers).get("x-zerogpu-token"),
      JSON.stringify({ encrypted: "zero-token-1", keyId: "hf-key-1" })
    );
  }
});

test("shared client refreshes a rejected ZeroGPU token once", async () => {
  let tokenRequests = 0;
  let submissions = 0;
  const sentTokens: string[] = [];
  const client = createGradioClient({
    getConfig: configFor,
    fetchImpl: mockFetch((url, init) => {
      if (isTokenUrl(url)) {
        tokenRequests += 1;
        return Response.json({ encryptedToken: `zero-token-${tokenRequests}` });
      }
      sentTokens.push(new Headers(init?.headers).get("x-zerogpu-token") ?? "");
      if (init?.method === "POST" && submissions++ === 0) {
        return new Response("", { status: 401 });
      }
      if (init?.method === "POST") return Response.json({ event_id: "job_123" });
      return completeResponse();
    })
  });

  await client.call({ service: "models", apiName: "sentiment", data: [["text"]] });
  assert.equal(tokenRequests, 2);
  assert.deepEqual(sentTokens, ["zero-token-1", "zero-token-2", "zero-token-2"]);
});

test("shared client refreshes its cached token after expiry", async () => {
  let now = 0;
  let tokenRequests = 0;
  const client = createGradioClient({
    getConfig: () => ({ ...configFor(), tokenExpiresInSeconds: 5 }),
    now: () => now,
    refreshSkewMs: 0,
    fetchImpl: mockFetch((url, init) => {
      if (isTokenUrl(url)) {
        tokenRequests += 1;
        return Response.json({ encryptedToken: `zero-token-${tokenRequests}` });
      }
      if (init?.method === "POST") return Response.json({ event_id: "job_123" });
      return completeResponse();
    })
  });

  await client.call({ service: "models", apiName: "sentiment", data: [[]] });
  now = 5001;
  await client.call({ service: "models", apiName: "sentiment", data: [[]] });
  assert.equal(tokenRequests, 2);
});

test("shared client preserves upstream HTTP status and keeps secrets out of errors", async () => {
  for (const status of [403, 429, 503]) {
    const client = createGradioClient({
      getConfig: configFor,
      fetchImpl: mockFetch((url) =>
        isTokenUrl(url)
          ? Response.json({ encryptedToken: "zero-token-secret" })
          : new Response("provider body must not be surfaced", { status })
      )
    });

    await assert.rejects(
      client.call({ service: "models", apiName: "sentiment", data: [[]] }),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(error.name, "AiIntegrationError");
        assert.equal("upstreamStatus" in error ? error.upstreamStatus : undefined, status);
        assert.ok(!error.message.includes("hf-secret-value"));
        assert.ok(!error.message.includes("zero-token-secret"));
        assert.ok(!error.message.includes("provider body"));
        return true;
      }
    );
  }
});

test("shared client rejects malformed event IDs before requesting an event stream", async () => {
  let resultRequests = 0;
  const client = createGradioClient({
    getConfig: configFor,
    fetchImpl: mockFetch((url, init) => {
      if (isTokenUrl(url)) return Response.json({ encryptedToken: "zero-token" });
      if (init?.method === "POST") return Response.json({ event_id: "bad/id" });
      resultRequests += 1;
      return completeResponse();
    })
  });

  await assert.rejects(
    client.call({ service: "models", apiName: "rag_answer", data: [] }),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "malformed_response"
  );
  assert.equal(resultRequests, 0);
});

test("shared client times out a stalled upstream request", async () => {
  const client = createGradioClient({
    getConfig: () => ({ ...configFor(), timeoutMs: 10 }),
    fetchImpl: mockFetch((url, init) => {
      if (isTokenUrl(url)) return Response.json({ encryptedToken: "zero-token" });
      return new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        if (signal?.aborted) reject(new Error("aborted"));
        else signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    })
  });

  await assert.rejects(
    client.call({ service: "models", apiName: "rag_answer", data: [] }),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "timeout"
  );
});

test("production rejects mock mode", () => {
  assert.throws(
    () =>
      getGradioRuntimeConfig("models", {
        NODE_ENV: "production",
        AI_SERVICE_USE_MOCKS: "true",
        HUGGINGFACE_ACCESS_TOKEN: "hf-secret-value"
      }),
    (error: unknown) =>
      error instanceof Error &&
      error.name === "AiIntegrationError" &&
      "kind" in error &&
      error.kind === "configuration"
  );
});

test("the shared external-service error maps to HTTP 502", () => {
  let statusCode = 0;
  let responseBody: unknown;
  const response = {
    status(code: number) {
      statusCode = code;
      return this;
    },
    json(body: unknown) {
      responseBody = body;
      return this;
    }
  };

  sendApiError(response as never, ERROR_CODES.EXTERNAL_SERVICE_ERROR);
  assert.equal(statusCode, 502);
  assert.ok(responseBody && typeof responseBody === "object");
});
