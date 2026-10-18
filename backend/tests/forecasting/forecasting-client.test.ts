import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildForecastData,
  buildForecastCsv,
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
  currency: "JOD",
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

test("Gradio /forecast receives its six-input typed API contract, not the /forecast_ui CSV contract", async () => {
  const calls: GradioCallInput[] = [];
  assert.deepEqual(buildForecastData(input), [
    [
      { transaction_date: "2026-10-01", quantity: 4, unit_price: 8, product_name: "Green tea" },
      { transaction_date: "2026-10-02", quantity: 0, unit_price: 8, product_name: "Green tea" }
    ],
    7,
    8,
    12,
    null,
    "Green tea"
  ]);
  const result = await requestDemandForecast(input, fakeClient(validResponse, calls));
  assert.equal(result.result.status === "OK" && result.result.expected_demand, 5);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.service, "analytics");
  assert.equal(calls[0]!.apiName, "forecast");
  assert.equal(calls[0]!.data.length, 6);
  assert.equal(calls[0]!.data[5], input.productName);
  assert.equal(calls[0]!.data[1], 7);
});

test("CSV preserves the selected product, actual currency, zero sales and quoted bilingual names", () => {
  const csv = buildForecastCsv({ ...input, productName: 'شاي, "Tea"\n500g', currency: 'jod' });
  assert.match(csv, /"شاي, ""Tea""\n500g",0,8,JOD,2026-10-02/);
  assert.equal(buildForecastData({ ...input, currentPrice: 0, currentStock: 0 })[3], 0);
  assert.equal(buildForecastData({ ...input, currentPrice: null, currentStock: null })[3], null);
  assert.equal(csv.includes('Wireless Mouse Pro'), false);
});

test("typed forecast payload preserves optional zero/null context and explicitly selects the product", () => {
  const productName = 'شاي, "Tea"\n500g';
  const data = buildForecastData({ ...input, productName, currentPrice: 0, currentStock: 0 });
  assert.equal(data[2], 0);
  assert.equal(data[3], 0);
  assert.equal(data[4], null);
  assert.equal(data[5], productName);
  assert.deepEqual((data[0] as any[]).map(row => row.product_name), [productName, productName]);
  const absent = buildForecastData({ ...input, currentPrice: null, currentStock: null });
  assert.equal(absent[2], null);
  assert.equal(absent[3], null);
});

test("valid UNKNOWN is unavailable rather than a malformed success or fabricated zero", async () => {
  const result = await requestDemandForecast(input, fakeClient({ ...validResponse, result: { status: "UNKNOWN" } }, []));
  assert.equal(result.result.status, "UNKNOWN");
  assert.equal("expected_demand" in result.result, false);
});
test("the supplied hosted baseline example is accepted without treating demo record IDs as tenant persistence", async () => {
  // The user's hosted-model example is a response-contract fixture only.
  const response = await requestDemandForecast({ ...input, productName: "Wireless Mouse Pro" }, fakeClient({
    product_name: "Wireless Mouse Pro", transactions_used: 21,
    result: { status: "OK", source: "baseline", forecast_id: "remote-forecast", evidence_id: "remote-evidence", expected_demand: 8, forecast_target_date: "2026-08-28", confidence_score: 0.2,
      data_sufficiency: { sufficient: false, available_days: 21, minimum_required: 30, confidence_status: "BUILDING" } },
    persisted_records: [{ table: "demand_forecasts", id: "remote-forecast", tenant_id: "public-demo-tenant", product_id: "requested-product", expected_demand: 8, forecast_target_date: "2026-08-28", confidence_range_lower: 6, confidence_range_upper: 10, model_version: "moving_average" }]
  }, []));
  assert.equal(response.transactions_used, 21);
  assert.equal(response.result.status, "OK");
  if (response.result.status === "OK") {
    assert.equal(response.result.expected_demand, 8);
    assert.equal(response.result.confidence_score, 0.2);
    assert.equal(response.result.source, "baseline");
    assert.equal("forecast_id" in response.result, false);
    assert.equal(response.result.model_version, undefined);
    assert.equal(response.result.confidence_range_lower, undefined);
  }
});
test("invalid calendar dates, unsupported period semantics and contradictory bounds fail closed", async () => {
  for (const update of [{ forecast_target_date: "2026-02-30" }, { prediction_kind: "period_total" },
    { confidence_range_lower: 6, confidence_range_upper: 8 }, { confidence_range_lower: 1 }, { status: "ERROR" }]) {
    await assert.rejects(requestDemandForecast(input, fakeClient({ ...validResponse, result: { ...validResponse.result, ...update } }, [])), (error: any) => error.kind === "malformed_response");
  }
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
