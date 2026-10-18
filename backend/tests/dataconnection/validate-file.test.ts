import assert from "node:assert/strict";
import test from "node:test";
import * as xlsx from "xlsx";
import {
  MAX_UPLOAD_SIZE_BYTES,
  validateExtractionUpload
} from "../../src/modules/dataconnection/types/dataconnection.validation.js";

const canonicalHeaders = [
  "product_name", "quantity", "unit_price", "currency", "transaction_date",
  "discount_pct", "invoice_id", "order_id", "email", "phone",
  "competitor_name", "amount_raw"
];

const posExportHeaders = [
  "Sale_ID", "Date_Time", "Product_ID", "Product_Name", "Quantity",
  "Unit_Price", "Total_Price", "Shift"
];

function upload(originalname: string, buffer: Buffer) {
  return { originalname, size: buffer.length, buffer };
}

function workbookBuffer(
  bookType: "xlsx" | "xlsm" = "xlsx",
  headers = canonicalHeaders,
  includeRow = true
): Buffer {
  const workbook = xlsx.utils.book_new();
  const rows: unknown[][] = [headers];
  if (includeRow) {
    rows.push([
      "Premium Olive Oil 1L", 3, 24.5, "JOD", "2026-08-30", 10,
      "INV-20458", "ORD-99231", "customer@example.com", "+962791234567",
      "Rival Store", 66.15
    ]);
  }
  xlsx.utils.book_append_sheet(workbook, xlsx.utils.aoa_to_sheet(rows), "Sales");
  return Buffer.from(xlsx.write(workbook, { type: "buffer", bookType }));
}

test("accepts the canonical AI sales template and rejects alias-only POS headers", () => {
  const canonicalCsv = Buffer.from(
    `${canonicalHeaders.join(",")}\nPremium Olive Oil 1L,3,24.50,JOD,2026-08-30,10,INV-20458,ORD-99231,customer@example.com,+962791234567,Rival Store,66.15\n`
  );
  const posCsv = Buffer.from(
    `${posExportHeaders.join(",")}\n100001,2025-01-01 15:34:00,p1-uuid,Micro USB Cable 1m,2,1.50,3,Evening\n`
  );

  assert.equal(validateExtractionUpload(upload("sales.csv", canonicalCsv)), null);
  assert.equal(validateExtractionUpload(upload("pos.csv", posCsv)), "TEMPLATE_MISMATCH");
  assert.equal(validateExtractionUpload(upload("sales.xlsx", workbookBuffer())), null);
  assert.equal(validateExtractionUpload(upload("sales.xlsm", workbookBuffer("xlsm"))), null);
});

test("rejects arbitrary Field/Value templates and blank template files", () => {
  const arbitraryCsv = Buffer.from("Field,Value,Date,Notes\ngross_margin,45,2025-12-31,Q4\n");
  const emptyTemplateCsv = Buffer.from(`${canonicalHeaders.join(",")}\n`);

  assert.equal(validateExtractionUpload(upload("generic.csv", arbitraryCsv)), "TEMPLATE_MISMATCH");
  assert.equal(validateExtractionUpload(upload("empty-template.csv", emptyTemplateCsv)), "TEMPLATE_MISMATCH");
  assert.equal(
    validateExtractionUpload(upload("empty-template.xlsx", workbookBuffer("xlsx", canonicalHeaders, false))),
    "TEMPLATE_MISMATCH"
  );
});

test("rejects the AI repository's internal sales_transactions_mock schema as an upload template", () => {
  const internalTransactionCsv = Buffer.from(
    "transaction_id,tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,converted_amount,converted_currency,exchange_rate,conversion_source,conversion_timestamp,sale_source,transaction_date,created_at\n" +
    "t1-uuid,tenant-alpha-123,p1-uuid,2,18.00,36.00,JOD,36.00,JOD,1.00000000,LOCAL,2026-07-27T10:00:00Z,POS,2026-07-27T10:00:00Z,2026-07-27T10:00:05Z\n"
  );

  assert.equal(
    validateExtractionUpload(upload("sales_transactions_mock.csv", internalTransactionCsv)),
    "TEMPLATE_MISMATCH"
  );
});

test("does not block valid PDF files locally; the parsed AI response is checked before persistence", () => {
  const pdf = Buffer.from("%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n");
  assert.equal(validateExtractionUpload(upload("sales.pdf", pdf)), null);
});

test("rejects unsupported extensions, content-extension mismatches, and malformed files", () => {
  const validCsv = Buffer.from(`${canonicalHeaders.join(",")}\nproduct,1,2,JOD,2026-08-30,,,,,,,\n`);
  assert.equal(validateExtractionUpload(upload("notes.txt", validCsv)), "INVALID_EXTENSION");
  assert.equal(
    validateExtractionUpload(upload("misnamed.csv", Buffer.from("%PDF-1.7\n%%EOF\n"))),
    "CONTENT_EXTENSION_MISMATCH"
  );
  assert.equal(validateExtractionUpload(upload("sales.pdf", validCsv)), "CONTENT_EXTENSION_MISMATCH");
  assert.equal(
    validateExtractionUpload(upload("sales.xlsx", Buffer.from("not an xlsx workbook"))),
    "CONTENT_EXTENSION_MISMATCH"
  );
  assert.equal(validateExtractionUpload(upload("empty.csv", Buffer.alloc(0))), "INVALID_SIZE");
});

test("rejects uploads over the configured AI extraction limit", () => {
  const tooLarge = Buffer.alloc(MAX_UPLOAD_SIZE_BYTES + 1);
  assert.equal(validateExtractionUpload(upload("large.csv", tooLarge)), "FILE_TOO_LARGE");
});
