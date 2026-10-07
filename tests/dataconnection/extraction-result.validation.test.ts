import assert from "node:assert/strict";
import test from "node:test";
import type { AiExtractionResponse } from "../../src/modules/dataconnection/client/ingestion.client.js";
import { validateExtractionResultForDataConnection } from "../../src/modules/dataconnection/validators/extraction-result.validation.js";

const canonicalHeaders = [
  "product_name", "quantity", "unit_price", "currency", "transaction_date",
  "discount_pct", "invoice_id", "order_id", "email", "phone",
  "competitor_name", "amount_raw"
];

function response(overrides: Partial<AiExtractionResponse> = {}): AiExtractionResponse {
  return {
    file_name: "sales.csv",
    detected_type: ".csv",
    headers: canonicalHeaders,
    rows_processed: 1,
    rows_truncated_to_limit: false,
    staged_row_count: 1,
    summary: {
      template_mode: "TEMPLATE_COMPLIANT",
      header_coverage_ratio: 1,
      rows_processed: 1,
      rows_partial: 0,
      rows_failed: 0,
      total_fields_expected: 12,
      total_fields_extracted: 12,
      row_outcomes: [
        {
          row_index: 0,
          mode: "TEMPLATE_COMPLIANT",
          parse_result: {
            typed_fields: {
              product_name: "Premium Olive Oil 1L",
              quantity: "2",
              unit_price: "1.5",
              currency: "JOD",
              transaction_date: "2025-01-01 15:34:00"
            }
          },
          field_errors: {},
          error: null
        }
      ]
    },
    ...overrides
  };
}

test("accepts a canonical AI extraction with all required sales fields", () => {
  assert.equal(validateExtractionResultForDataConnection(response()), null);
});

test("rejects fallback-only output and generic unmapped headers", () => {
  const fallback = response({
    headers: ["Field", "Value", "Date", "Notes"],
    summary: {
      ...response().summary,
      template_mode: "FALLBACK",
      header_coverage_ratio: 0,
      row_outcomes: [
        {
          row_index: 0,
          mode: "FALLBACK",
          parse_result: { typed_fields: {} },
          field_errors: {},
          error: null
        }
      ]
    }
  });

  assert.match(validateExtractionResultForDataConnection(fallback) ?? "", /headers/);
});

test("rejects row errors, invalid fields, and missing required typed values", () => {
  const errored = response({
    summary: {
      ...response().summary,
      rows_partial: 1,
      row_outcomes: [
        {
          ...response().summary.row_outcomes[0]!,
          field_errors: { unit_price: "Invalid numeric value" }
        }
      ]
    }
  });
  const missingQuantity = response({
    summary: {
      ...response().summary,
      row_outcomes: [
        {
          ...response().summary.row_outcomes[0]!,
          parse_result: {
            typed_fields: {
              product_name: "Micro USB Cable 1m",
              unit_price: "1.5"
            }
          }
        }
      ]
    }
  });

  assert.match(validateExtractionResultForDataConnection(errored) ?? "", /failed sales-data validation/);
  assert.match(validateExtractionResultForDataConnection(missingQuantity) ?? "", /quantity/);
});

test("rejects alias-only AI recognition even when the core three fields were extracted", () => {
  const aliases = ["Product_Name", "Quantity", "Unit_Price", "Total_Price", "Shift"];
  const canonical = response({
    headers: aliases,
    summary: {
      ...response().summary,
      template_mode: "RECOGNIZED",
      header_coverage_ratio: 0.6,
      row_outcomes: [
        {
          ...response().summary.row_outcomes[0]!,
          mode: "RECOGNIZED",
          parse_result: {
            typed_fields: {
              product_name: "AA Battery Pack (4pcs)",
              quantity: "3",
              unit_price: "2"
            }
          }
        }
      ]
    }
  });

  assert.match(validateExtractionResultForDataConnection(canonical) ?? "", /headers/);
});
