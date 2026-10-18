import assert from "node:assert/strict";
import { test } from "node:test";
import { perceptionPresentation } from "../src/features/market-intelligence/utils/marketPerceptionPresentation.js";
import { prepareMarketExport } from "../src/features/market-intelligence/utils/marketIntelligencePresentation.js";
import { readFileSync } from "node:fs";
const valid = { status: "OK", reason: null, mpi: 0, sample_size: { status: "OK", minimum_required: 5 }, review_count: 5,
  confidence_score: 0, analysis_performed: true, label_counts: { positive: 0, neutral: 0, negative: 5 }, evidence: { source_review_ids: ["source"] } };
test("a valid zero MPI/confidence survives formatting; provisional low samples do not become scores", () => {
  const zero = perceptionPresentation(valid);
  assert.equal(zero.score, 0); assert.equal(zero.confidence, 0); assert.equal(zero.dominantLabel, "negative");
  const thin = perceptionPresentation({ ...valid, status: "UNKNOWN", reason: "INSUFFICIENT_REVIEWS", mpi: 90 });
  assert.equal(thin.score, null); assert.equal(thin.status, "INSUFFICIENT_REVIEWS");
});
test("tied labels stay mixed and unavailable states remain distinct", () => {
  const tied = perceptionPresentation({ ...valid, mpi: 50, label_counts: { positive: 2, negative: 2, neutral: 1 } });
  assert.equal(tied.dominantLabel, null);
  for (const state of ["NO_ELIGIBLE_REVIEWS", "INSUFFICIENT_REVIEWS", "SERVICE_UNAVAILABLE", "SUBJECT_UNAVAILABLE"]) {
    assert.equal(perceptionPresentation(null, state).status, state);
  }
  assert.equal(perceptionPresentation({ ...valid, mpi: 101 }, "OK").status, "MODEL_UNAVAILABLE");
});
test("unauthorized PDF export removes nested MPI evidence, not just the displayed label", () => {
  const data = { competitors: [{ marketPerceptionSummary: valid, marketPerceptionStatus: "OK", marketPerceptionScore: 0 }] };
  const exported = prepareMarketExport(data, {});
  assert.equal(exported.competitors[0].marketPerceptionSummary, null);
  assert.equal(exported.competitors[0].marketPerceptionStatus, "NOT_INCLUDED");
  assert.equal(data.competitors[0].marketPerceptionSummary, valid);
});
test("all perception translation keys and states match across Arabic and English", () => {
  const read = (lang) => JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`, import.meta.url))).marketPerception;
  const flatten = (value, prefix = "") => Object.entries(value).flatMap(([key, item]) => typeof item === "object" ? flatten(item, `${prefix}${key}.`) : [`${prefix}${key}`]).sort();
  assert.deepEqual(flatten(read("en")), flatten(read("ar")));
});
