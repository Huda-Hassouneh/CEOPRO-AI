import assert from "node:assert/strict";
import test from "node:test";
import { uploadExtractionFile } from "../../src/modules/dataconnection/client/ingestion.client.js";

const validResponse = {
  file_name: "sales.csv", detected_type: "csv",
  headers: ["product_name", "quantity", "unit_price", "currency", "transaction_date"],
  rows_processed: 1, rows_truncated_to_limit: false, staged_row_count: 1,
  summary: {
    template_mode: "TEMPLATE_COMPLIANT", header_coverage_ratio: 1,
    rows_processed: 1, rows_partial: 0, rows_failed: 0,
    total_fields_expected: 5, total_fields_extracted: 5,
    row_outcomes: [{ row_index: 0, mode: "TEMPLATE_COMPLIANT", field_errors: [],
      parse_result: { typed_fields: { product_name: "Olive Oil", quantity: 1, unit_price: 4, currency: "JOD", transaction_date: "2026-10-01" } } }]
  }
};

test("Gradio contract sends sanitized filename, Base64 bytes, country, and currency", async () => {
  const bytes = Buffer.from("product_name,quantity\nOlive Oil,1\n");
  let call: any;
  const client = { call: async (request: any) => { call = request; return validResponse; } };
  await uploadExtractionFile({ file: { originalname: "../sales.csv", buffer: bytes } }, client as any);
  assert.equal(call.service, "analytics");
  assert.equal(call.apiName, "extract_file");
  assert.deepEqual(call.data, ["sales.csv", bytes.toString("base64"), "JO", "JOD"]);
});

test("Gradio contract forwards explicit locale context and timeout", async () => {
  let call: any;
  const client = { call: async (request: any) => { call = request; return validResponse; } };
  await uploadExtractionFile({
    file: { originalname: "sale.csv", buffer: Buffer.from("x") },
    countryCode: "SA", currency: "SAR", timeoutMs: 1234
  }, client as any);
  assert.deepEqual(call.data.slice(2), ["SA", "SAR"]);
  assert.equal(call.timeoutMs, 1234);
});

test("malformed AI payload is rejected without embedding extracted response values in the error", async () => {
  const client = { call: async () => ({ file_name: "secret-customer.csv", rows_processed: "one" }) };
  await assert.rejects(
    uploadExtractionFile({ file: { originalname: "sale.csv", buffer: Buffer.from("x") } }, client as any),
    (error: Error) => error.message.includes("malformed_response") === false &&
      error.message.includes("secret-customer.csv") === false
  );
});
