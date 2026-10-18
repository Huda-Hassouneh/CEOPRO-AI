import assert from "node:assert/strict";
import { test } from "node:test";
import { eligibleMpiReviews, mpiSampleDecision, validateMpiSubject } from "../../src/modules/mpi/service/mpi.policy.js";
import { mpiSummaryQuerySchema } from "../../src/modules/mpi/types/mpi.validation.js";

const id = "12345678-1234-4234-8234-123456789abc";
const asOf = new Date("2026-10-12T00:00:00Z");
const review = { review_id: "r", review_text: "Good", review_date: asOf, collection_method: "MANUAL" };

test("product/competitor queries require a UUID and business context cannot target another tenant", () => {
  for (const subject_type of ["PRODUCT", "COMPETITOR"]) {
    assert.equal(mpiSummaryQuerySchema.safeParse({ subject_type }).success, false);
    assert.equal(mpiSummaryQuerySchema.safeParse({ subject_type, subject_id: "bad" }).success, false);
    assert.equal(mpiSummaryQuerySchema.safeParse({ subject_type, subject_id: id }).success, true);
  }
  assert.equal(mpiSummaryQuerySchema.safeParse({ subject_type: "BUSINESS" }).success, true);
  assert.throws(() => validateMpiSubject({ tenantId: id, subjectType: "BUSINESS", subjectId: "other" }));
  assert.doesNotThrow(() => validateMpiSubject({ tenantId: id, subjectType: "BUSINESS", subjectId: id.toUpperCase() }));
});

test("eligible sampling rejects blank/future/invalid/method-ineligible rows and duplicate IDs", () => {
  const rows = [review, review,
    { ...review, review_id: "blank", review_text: "   \n" },
    { ...review, review_id: "future", review_date: new Date("2026-10-13") },
    { ...review, review_id: "invalid", review_date: new Date("bad") },
    { ...review, review_id: "method", collection_method: "SCRAPED" }];
  assert.deepEqual(eligibleMpiReviews(rows, asOf), [review]);
  const many = Array.from({ length: 105 }, (_, index) => ({ ...review, review_id: `r-${index}` }));
  assert.equal(eligibleMpiReviews(many, asOf).length, 100);
});

test("sample floor and explicit model low/unknown metadata cannot be promoted to OK", () => {
  assert.equal(mpiSampleDecision(1, 1).status, "LOW_SAMPLE_SIZE");
  assert.equal(mpiSampleDecision(5, 5).status, "OK");
  assert.equal(mpiSampleDecision({ status: "LOW_SAMPLE_SIZE" }, 20).status, "LOW_SAMPLE_SIZE");
  assert.equal(mpiSampleDecision({ status: "UNKNOWN" }, 20).status, "UNKNOWN");
  assert.equal(mpiSampleDecision({ status: "OK", sufficient: false, analyzed_count: 20 }, 20).status, "LOW_SAMPLE_SIZE");
  assert.equal(mpiSampleDecision({ status: "OK", minimum_required: 10 }, 5).status, "LOW_SAMPLE_SIZE");
  assert.equal(mpiSampleDecision({ status: "OK", minimum_required: 2 }, 4).minimum_required, 5);
});
