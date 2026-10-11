import assert from "node:assert/strict";
import test from "node:test";
import type { GradioClient } from "../../src/integrations/ai/ai.types.js";
import {
  buildPricingGradioData,
  readPricingExplanation,
  requestPricingRecommendation,
  type PricingGradioResponse
} from "../../src/modules/pricing/client/pricing.client.js";
import type { AiPricingRequest } from "../../src/modules/pricing/types/pricing.types.js";

const input: AiPricingRequest = {
  product: { product_name: "Coffee machine", current_price: 100, currency: "JOD", cost_price: 55 },
  competitorPrices: [
    { competitor_name: "A", price: 80, currency: "JOD", observed_at: "2026-10-10" },
    { competitor_name: "B", price: 120, currency: "USD", observed_at: "2026-10-10" }
  ],
  exchangeRates: [{ from_currency: "USD", to_currency: "JOD", rate: 0.71, as_of: "2026-10-10", source: "fixture" }]
};

const ok = (patch: Record<string, unknown> = {}) => ({
  result: {
    status: "OK", action: "lower", current_price: 100, suggested_price: 85,
    guardrail_clamped: true, margin_guardrail_clamped: false,
    matched_competitor_count: 2, confidence_score: 0.55, ...patch
  },
  persisted_records: [{ explanation_text: "Rule based market comparison." }]
});

function fakeClient(payload: unknown, onCall?: (args: unknown) => void): GradioClient {
  return {
    call: async (args) => { onCall?.(args); return payload; }
  } as unknown as GradioClient;
}

test("pricing Gradio call serializes the exact three positional inputs and preserves currency metadata", async () => {
  let request: unknown;
  await requestPricingRecommendation(input, fakeClient(ok(), (args) => { request = args; }));
  assert.deepEqual(request, {
    service: "analytics",
    apiName: "recommend",
    data: buildPricingGradioData(input)
  });
  assert.deepEqual(buildPricingGradioData(input), [
    { product_name: "Coffee machine", current_price: 100, currency: "JOD", cost_price: 55 },
    [
      { competitor_name: "A", price: 80, currency: "JOD", observed_at: "2026-10-10" },
      { competitor_name: "B", price: 120, currency: "USD", observed_at: "2026-10-10" }
    ],
    [{ from_currency: "USD", to_currency: "JOD", rate: 0.71, as_of: "2026-10-10", source: "fixture" }]
  ]);
});

test("Gradio contract accepts each documented action and UNKNOWN separately", async () => {
  for (const action of ["raise", "lower", "hold"] as const) {
    const response = await requestPricingRecommendation(input, fakeClient(ok({ action })));
    assert.equal(response.result.status, "OK");
    if (response.result.status === "OK") assert.equal(response.result.action, action);
  }
  const unknown = await requestPricingRecommendation(input, fakeClient({
    result: { status: "UNKNOWN" }, persisted_records: []
  }));
  assert.deepEqual(unknown.result, { status: "UNKNOWN" });
});

test("malformed, unsafe, or unsupported Gradio values fail closed", async () => {
  const invalid: unknown[] = [
    null,
    {},
    { result: null, persisted_records: [] },
    { result: { ...ok().result, action: "apply_price" }, persisted_records: [] },
    { result: { ...ok().result, suggested_price: -1 }, persisted_records: [] },
    { result: { ...ok().result, suggested_price: Infinity }, persisted_records: [] },
    { result: { ...ok().result, confidence_score: 1.01 }, persisted_records: [] },
    { result: { ...ok().result, matched_competitor_count: 1.5 }, persisted_records: [] },
    { result: { status: "OK", action: "hold" }, persisted_records: [] },
    { result: { status: "UNKNOWN" } },
    { result: { status: "ERROR" }, persisted_records: [] }
  ];
  for (const payload of invalid) {
    await assert.rejects(
      requestPricingRecommendation(input, fakeClient(payload)),
      (error: unknown) => error instanceof Error && error.name === "AiIntegrationError"
    );
  }
});

test("persisted explanation is optional and extracted only from provider persisted records", () => {
  const response = ok() as PricingGradioResponse;
  assert.equal(readPricingExplanation(response), "Rule based market comparison.");
  assert.equal(readPricingExplanation({ result: { status: "UNKNOWN" }, persisted_records: [] }), null);
});

test("an explanation without observation identities is not treated as complete provenance", async () => {
  const response = await requestPricingRecommendation(input, fakeClient(ok()));
  const record = response.persisted_records[0] as Record<string, unknown>;
  assert.equal(typeof record.explanation_text, "string");
  assert.equal("competitor_price_ids" in record, false);
});
