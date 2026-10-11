import assert from "node:assert/strict";
import test from "node:test";
import * as xlsx from "xlsx";
import {
  MAX_UPLOAD_SIZE_BYTES,
  validateExtractionUpload
} from "../../src/modules/dataconnection/types/dataconnection.validation.js";

const headers = "product_name,quantity,unit_price,currency,transaction_date";
function csvOfSize(size: number): Buffer {
  const prefix = `${headers}\n\"`;
  const suffix = `\",1,1.00,JOD,2026-10-01\n`;
  assert.ok(size >= Buffer.byteLength(prefix + "x" + suffix));
  return Buffer.from(prefix + "x".repeat(size - Buffer.byteLength(prefix + suffix)) + suffix);
}
function upload(name: string, buffer: Buffer) {
  return { originalname: name, size: buffer.length, buffer };
}

test("upload limit is the configured MAX_UPLOAD_BYTES value or the 10 MiB default", () => {
  assert.equal(MAX_UPLOAD_SIZE_BYTES, Number(process.env.MAX_UPLOAD_BYTES) || 10 * 1024 * 1024);
});

test("valid canonical CSV accepts one byte below and exactly at the backend byte limit", () => {
  for (const size of [MAX_UPLOAD_SIZE_BYTES - 1, MAX_UPLOAD_SIZE_BYTES]) {
    const file = csvOfSize(size);
    assert.equal(file.length, size);
    assert.equal(validateExtractionUpload(upload("sales.csv", file)), null);
  }
});

test("one byte above the backend limit is rejected before content parsing", () => {
  const file = Buffer.alloc(MAX_UPLOAD_SIZE_BYTES + 1, 0x20);
  assert.equal(validateExtractionUpload(upload("large.csv", file)), "FILE_TOO_LARGE");
});

test("canonical CSV and XLSX are accepted, while legacy XLS and image formats are not", () => {
  const csv = Buffer.from(`${headers}\nArabic زيت زيتون,2,3.25,JOD,2026-10-01\n`);
  const book = xlsx.utils.book_new();
  xlsx.utils.book_append_sheet(book, xlsx.utils.aoa_to_sheet([
    headers.split(","), ["Arabic زيت زيتون", 2, 3.25, "JOD", "2026-10-01"]
  ]), "Sales");
  const xlsxBytes = Buffer.from(xlsx.write(book, { type: "buffer", bookType: "xlsx" }));
  assert.equal(validateExtractionUpload(upload("sales.csv", csv)), null);
  assert.equal(validateExtractionUpload(upload("sales.xlsx", xlsxBytes)), null);
  assert.equal(validateExtractionUpload(upload("legacy.xls", xlsxBytes)), "INVALID_EXTENSION");
  assert.equal(validateExtractionUpload(upload("photo.png", Buffer.from("\x89PNG\r\n\x1a\n"))), "INVALID_EXTENSION");
});

test("missing, empty, signature-mismatched, and header-only documents are rejected", () => {
  assert.equal(validateExtractionUpload(undefined), "MISSING_FILE");
  assert.equal(validateExtractionUpload(upload("empty.csv", Buffer.alloc(0))), "INVALID_SIZE");
  assert.equal(validateExtractionUpload(upload("wrong.csv", Buffer.from("%PDF-1.7\n%%EOF"))), "CONTENT_EXTENSION_MISMATCH");
  assert.equal(validateExtractionUpload(upload("headers.csv", Buffer.from(`${headers}\n`))), "TEMPLATE_MISMATCH");
});
