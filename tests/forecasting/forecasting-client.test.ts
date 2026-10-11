import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildForecastData,
  requestDemandForecast,
  type ForecastRequestInput
} from "../../src/modules/forecasting/client/forecasting.client.js";
import type { GradioCallInput, GradioClient } from "../../src/integrations/ai/ai.types.js";

const input: ForecastRequestInput = {
  transactions: [
    { transaction_date: "2026-10-01", quantity: 4, unit_price: 8 },
    { transaction_date: "2026-10-02", quantity: 0, unit_price: 8 }
  ],
  horizonDays: 7,
  currentPrice: 8,
  currentStock: 12,
  category: "tea",
  productName: "Green tea"
};

const validResponse = {
  product_name: "Green tea",
  transactions_used: 2,
  result: {
    status: "OK",
    source: "baseline",
    expected_demand: 5,
    forecast_target_date: "2026-10-09",
    confidence_score: 0.4,
    data_sufficiency: { available_days: 2, minimum_required: 28 }
  },
  persisted_records: []
};

function fakeClient(payload: unknown, calls: GradioCallInput[]): GradioClient {
  return {
    async call(call) {
      calls.push(call);
      return payload;
    }
  };
}

test("Gradio forecasting request uses analytics/forecast and the positional six-field payload", async () => {
  const calls: GradioCallInput[] = [];
  assert.deepEqual(buildForecastData(input), [
    input.transactions,
    7,
    8,
    12,
    "tea",
    "Green tea"
  ]);
  const result = await requestDemandForecast(input, fakeClient(validResponse, calls));
  assert.equal(result.result.expected_demand, 5);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.service, "analytics");
  assert.equal(calls[0]!.apiName, "forecast");
  assert.equal(calls[0]!.data.length, 6);
  assert.equal(calls[0]!.data[1], 7);
});

test("forecast client rejects a horizon outside 1..60 before calling AI", async () => {
  const calls: GradioCallInput[] = [];
  for (const horizonDays of [0, -1, 61, 1.5]) {
    await assert.rejects(
      requestDemandForecast({ ...input, horizonDays }, fakeClient(validResponse, calls)),
      (error: any) => error?.kind === "configuration"
    );
  }
  assert.equal(calls.length, 0);
});

test("forecast client rejects malformed, missing, negative, and non-finite prediction fields", async () => {
  const invalidResponses: unknown[] = [
    null,
    {},
    { ...validResponse, result: { ...validResponse.result, expected_demand: null } },
    { ...validResponse, result: { ...validResponse.result, expected_demand: "5" } },
    { ...validResponse, result: { ...validResponse.result, expected_demand: -1 } },
    { ...validResponse, result: { ...validResponse.result, confidence_score: 1.1 } },
    { ...validResponse, result: { ...validResponse.result, source: "unknown-model" } }
  ];
  for (const payload of invalidResponses) {
    await assert.rejects(
      requestDemandForecast(input, fakeClient(payload, [])),
      (error: any) => error?.kind === "malformed_response"
    );
  }
});
