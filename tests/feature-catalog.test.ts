import assert from "node:assert/strict";
import test from "node:test";
import {
  CANONICAL_FEATURES,
  CANONICAL_FEATURE_CODES
} from "../src/modules/features/catalog.js";

test("canonical catalog contains exactly 21 unique features", () => {
  assert.equal(CANONICAL_FEATURES.length, 21);
  assert.equal(new Set(CANONICAL_FEATURE_CODES).size, 21);
});

test("canonical SUM features reset each billing period", () => {
  const expected = new Set([
    "ai_pricing",
    "sentiment_analysis",
    "rag_assistant",
    "document_extraction",
    "report_generation",
    "marketing_image_generation"
  ]);

  for (const feature of CANONICAL_FEATURES) {
    if (!expected.has(feature.code)) continue;
    assert.equal(feature.type, "limit");
    assert.equal(feature.aggregationType, "sum");
    assert.equal(feature.resetCycle, "billing_period");
  }
});

test("canonical MAX capacity features are lifetime capacities", () => {
  const expected = new Set([
    "tracked_competitors",
    "tracked_products",
    "connected_data_sources",
    "team_members",
    "document_storage_gb"
  ]);

  for (const feature of CANONICAL_FEATURES) {
    if (!expected.has(feature.code)) continue;
    assert.equal(feature.type, "limit");
    assert.equal(feature.aggregationType, "max");
    assert.equal(feature.resetCycle, "lifetime");
  }
});
