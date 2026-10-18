import assert from "node:assert/strict";
import test from "node:test";
import { extractCompleteSalesCsv, verifyCommittedCsvPrefix, SalesCsvImportError } from "../../src/modules/dataconnection/service/sales-csv-import.js";

const header = "product_name,quantity,unit_price,currency,transaction_date,order_id";
const parse = (rows: string) => extractCompleteSalesCsv("sales.csv", Buffer.from(`${header}\n${rows}`));
const old = (payload: unknown, index = 0) => ({ raw_payload_json: payload, validation_status: "COMMITTED", committed_table: "transactions", committed_record_id: `sale-${index}` });

test("imports every record beyond a 1,000-row preview and preserves duplicate sales", () => {
  const result = parse(Array.from({ length: 1503 }, (_, i) => `Orange Juice 1L,2,2.95,JOD,2026-10-08,ORD-${i}`).join("\n"));
  assert.equal(result.summary.row_outcomes.length, 1503);
  assert.equal(result.rows_processed, 1503);
  assert.equal(result.staged_row_count, 1503);
  assert.equal(result.rows_truncated_to_limit, false);
  assert.equal(result.summary.row_outcomes[1502]?.parse_result?.typed_fields.order_id, "ORD-1502");
});

test("CSV parsing preserves BOM, quoted commas, newlines, quotes, Arabic and leading-zero identifiers", () => {
  const bytes = Buffer.from(`\uFEFF${header}\r\n"زيت, \"\"ممتاز\"\"\nOlive",2,3.25,JOD,2026-10-08,000123\r\n\r\n`);
  const fields = extractCompleteSalesCsv("sales.csv", bytes).summary.row_outcomes[0]?.parse_result?.typed_fields;
  assert.equal(fields?.product_name, 'زيت, "ممتاز"\nOlive');
  assert.equal(fields?.order_id, "000123");
});

test("rejects a malformed or invalid record even after the first 1,000 valid rows", () => {
  const rows = Array.from({ length: 1000 }, () => "Tea,2,3.25,JOD,2026-10-08,A").join("\n");
  for (const bad of ['"Tea"junk,2,3.25,JOD,2026-10-08,A', 'Tea,2,3.25,JOD,2026-10-08,A,extra', 'Tea,-2,3.25,JOD,2026-10-08,A', 'Tea,2,3.25,JOD,2026-02-30,A']) {
    assert.throws(() => parse(`${rows}\n${bad}`), SalesCsvImportError);
  }
});

test("recovery proves each committed prefix row, including decimal normalization and audit IDs", () => {
  const result = parse("Tea,2,3.25,JOD,2026-10-08,A\nTea,2,3.25,JOD,2026-10-08,B\nTea,2,3.25,JOD,2026-10-08,C");
  const outcomes = result.summary.row_outcomes;
  const previous = [old({ ...outcomes[0]!.parse_result!.typed_fields, quantity: 2, unit_price: 3.25 }), old(outcomes[1]!.parse_result!.typed_fields, 1)];
  assert.doesNotThrow(() => verifyCommittedCsvPrefix(previous, outcomes));
  for (const bad of [
    [{ ...previous[0]!, validation_status: "PENDING" }],
    [{ ...previous[0]!, committed_record_id: null }],
    [old({ ...previous[0]!.raw_payload_json as object, quantity: 9 })],
    [old({ ...previous[0]!.raw_payload_json as object, order_id: "DIFFERENT" })],
    [previous[1]!, previous[0]!], [], outcomes.map((row, i) => old(row.parse_result!.typed_fields, i))
  ]) assert.throws(() => verifyCommittedCsvPrefix(bad, outcomes), SalesCsvImportError);
});
