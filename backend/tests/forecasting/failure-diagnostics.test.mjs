import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { createAiIntegrationError } from "../../src/integrations/ai/ai.types.ts";
let failure;
await mock.module("../../src/modules/forecasting/service/forecasting.service.ts", { namedExports: {
  generateDemandForecast: async () => { throw failure; },
  getDemandDetail: async () => { throw Error("unexpected read"); },
  getDemandOverview: async () => { throw Error("unexpected read"); }
} });
const { generateDemand } = await import("../../src/modules/forecasting/controller/forecasting.controller.ts");
const request = { tenant_id: "tenant", user: { user_id: "user" }, params: { productId: "11111111-1111-4111-8111-111111111111" }, body: { horizon_days: 7 } };
const cases = [
  ["configuration", "HUGGINGFACE_ACCESS_TOKEN is required for the AI service.", undefined, "FORECAST_AI_TOKEN_MISSING", "configuration"],
  ["network", "Hugging Face ZeroGPU authentication request failed.", undefined, "FORECAST_AI_CONNECTION_FAILED", "authentication"],
  ["timeout", "The Gradio SSE stream timed out after 180000 ms.", undefined, "FORECAST_AI_TIMEOUT", "result"],
  ["upstream_event", "The Gradio AI job returned an error event.", undefined, "FORECAST_AI_EXECUTION_FAILED", "result"],
  ["malformed_response", "Gradio forecasting response did not match the documented output schema.", undefined, "FORECAST_AI_INVALID_RESPONSE", "validation"],
  ["malformed_response", "Forecast target does not match the supplied history and horizon.", undefined, "FORECAST_AI_TARGET_MISMATCH", "validation"],
  ["malformed_response", "Forecasting returned a different product.", undefined, "FORECAST_AI_PRODUCT_MISMATCH", "validation"],
  ["upstream_http", "Gradio job submission returned HTTP 401.", 401, "FORECAST_AI_AUTHENTICATION_FAILED", "submission"],
  ["upstream_http", "Gradio job submission returned HTTP 429.", 429, "FORECAST_AI_RATE_LIMITED", "submission"],
  ["upstream_http", "Gradio result retrieval returned HTTP 503.", 503, "FORECAST_AI_HTTP_ERROR", "result"]
];
for (const [kind, message, status, reason, stage] of cases) test(`forecast failure ${kind}/${reason} retains safe cause and stage`, async () => {
  failure = createAiIntegrationError(message, kind, status);
  const res = { code: null, body: null, status(n) { this.code = n; return this; }, json(body) { this.body = body; return this; } };
  const original = console.warn; const logs = []; console.warn = (...args) => logs.push(args);
  try { await generateDemand(request, res, (err) => { throw err; }); } finally { console.warn = original; }
  assert.equal(res.code, 502); assert.equal(res.body.error.details.reason, reason);
  assert.equal(res.body.error.details.failure_kind, kind); assert.equal(res.body.error.details.stage, stage);
  assert.equal(res.body.error.details.upstream_status, status ?? null); assert.equal(logs.length, 1);
});
test("untrusted upstream messages, credentials and payloads never reach response or logs", async () => {
  failure = createAiIntegrationError("secret token=example-private-value product=PRIVATE_SALE", "malformed_response");
  const res = { body: null, status() { return this; }, json(body) { this.body = body; return this; } };
  const original = console.warn; let logged; console.warn = (...args) => { logged = args; };
  try { await generateDemand(request, res, (err) => { throw err; }); } finally { console.warn = original; }
  assert.doesNotMatch(JSON.stringify([res.body, logged]), /example-private-value|PRIVATE_SALE/);
});
