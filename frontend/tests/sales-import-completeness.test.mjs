import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { confirmSalesImport } from "../src/features/data-ingestion/utils/salesImportConfirmation.js";
const complete = { job_id: "job", job_id_source: "ceopro", job_status: "queued", rows_truncated_to_limit: false, import_complete: true, source_rows_total: 39498, staged_row_count: 39498 };
test("accepts a complete queued file, recovered job and complete duplicate", () => {
  for (const extra of [{}, { recovered: true, added_row_count: 38498 }, { duplicate: true, job_status: "completed" }]) {
    const payload = { ...complete, ...extra }; assert.equal(confirmSalesImport(payload), payload);
  }
});
test("never reports a truncated or inconsistent upload as a success or duplicate", () => {
  for (const extra of [{ rows_truncated_to_limit: true }, { rows_truncated_to_limit: 1000 }, { import_complete: false, duplicate: true }, { staged_row_count: 1000 }, { job_id_source: "provider" }, { job_status: "extracting" }]) {
    assert.throws(() => confirmSalesImport({ ...complete, ...extra }));
  }
});
test("English and Arabic explain source totals, processing and safe recovery", () => {
  for (const locale of ["en", "ar"]) {
    const copy = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), "utf8")).connectData;
    for (const key of ["sourceRows", "incomplete", "truncatedHelp"]) assert.ok(copy.job[key]);
    for (const key of ["salesRowsReceived", "salesRowsRecovered"]) assert.ok(copy.feedback[key]);
  }
});
