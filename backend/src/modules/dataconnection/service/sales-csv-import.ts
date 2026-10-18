import * as xlsx from "xlsx";
import { extname } from "node:path";
import { saleIdentity } from "./sale-identity.js";
import type { AiExtractionResponse } from "../client/ingestion.client.js";
import type { ExtractionRowOutcome } from "../types/dataconnection.types.js";
import { readSalesCsv } from "../validators/extraction-template.validation.js";
import { parseSalesStagingRow } from "./sales-staging-row.js";

export class SalesCsvImportError extends Error {
  constructor(message: string) { super(message); this.name = "SalesCsvImportError"; }
}

/** Canonical sales CSV is already structured data; read the actual file locally. */
export function extractCompleteSalesCsv(fileName: string, buffer: Buffer): AiExtractionResponse {
  const csv = readSalesCsv(buffer);
  if (!csv) throw new SalesCsvImportError("The sales CSV is malformed or does not match the required template.");
  const outcomes: ExtractionRowOutcome[] = csv.rows.map((row, index) => {
    if (row.length !== csv.headers.length) {
      throw new SalesCsvImportError(`CSV record ${index + 2} has a different number of columns than the header.`);
    }
    const fields: Record<string, unknown> = {};
    csv.headers.forEach((header, column) => {
      // Preserve extra columns as supplied, while normalizing canonical header spelling.
      fields[csv.assessment.headerMapping[header] ?? header] = row[column]!;
    });
    const parsed = parseSalesStagingRow(fields);
    if (!parsed.ok) throw new SalesCsvImportError(`CSV record ${index + 2}: ${parsed.error}`);
    try { saleIdentity(fields, parsed.value); }
    catch (error) { throw new SalesCsvImportError(`CSV record ${index + 2}: ${(error as Error).message}`); }
    return { row_index: index, mode: "TEMPLATE_COMPLIANT", parse_result: { typed_fields: fields }, field_errors: [], error: null };
  });
  return {
    file_name: fileName, detected_type: "csv", headers: csv.headers,
    rows_processed: outcomes.length, rows_truncated_to_limit: false, staged_row_count: outcomes.length,
    summary: {
      template_mode: "TEMPLATE_COMPLIANT", header_coverage_ratio: csv.assessment.coverageRatio,
      rows_processed: outcomes.length, rows_partial: 0, rows_failed: 0,
      total_fields_expected: csv.headers.length * outcomes.length,
      total_fields_extracted: csv.headers.length * outcomes.length,
      row_outcomes: outcomes
    }
  };
}

/** Canonical workbooks are structured data too; read every row without a hosted row cap. */
export function extractCompleteSalesFile(fileName: string, buffer: Buffer): AiExtractionResponse {
  const extension = extname(fileName).toLowerCase();
  if (extension === ".csv") return extractCompleteSalesCsv(fileName, buffer);
  try {
    const workbook = xlsx.read(buffer, { type: "buffer", cellDates: true });
    const sheets = workbook.SheetNames.filter(name => {
      const rows = xlsx.utils.sheet_to_json(workbook.Sheets[name]!, { header: 1 });
      return rows.length > 0;
    });
    // Multiple sheets must not be silently skipped. Use one canonical sales sheet.
    if (sheets.length !== 1) throw new Error("Use exactly one non-empty sales worksheet.");
    const sheet = workbook.Sheets[sheets[0]!]!;
    for (const [key, cell] of Object.entries(sheet)) {
      if (key.startsWith("!")) continue;
      if (cell.t === "d" && cell.v instanceof Date) {
        cell.t = "s"; cell.v = cell.v.toISOString(); delete cell.w;
      }
    }
    const result = extractCompleteSalesCsv(fileName, Buffer.from(xlsx.utils.sheet_to_csv(sheet)));
    return { ...result, detected_type: extension.slice(1) };
  } catch (error) {
    throw new SalesCsvImportError(`Sales workbook: ${(error as Error).message}`);
  }
}

function saleKey(payload: unknown): string | null {
  const parsed = parseSalesStagingRow(payload);
  if (!parsed.ok) return null;
  const v = parsed.value;
  return JSON.stringify([v.productName, v.sku, v.quantity, v.unitPrice, v.totalPrice, v.currency, v.transactionDate.toISOString()]);
}

/** Prove the old staging records are the same ordered prefix before appending. */
export function verifyCommittedCsvPrefix(existing: Array<{
  raw_payload_json: unknown;
  validation_status: string;
  committed_table: string | null;
  committed_record_id: string | null;
}>, outcomes: ExtractionRowOutcome[]): void {
  if (existing.length === 0 || existing.length >= outcomes.length) {
    throw new SalesCsvImportError("The previous import is not a recoverable partial CSV import.");
  }
  for (const [index, row] of existing.entries()) {
    const incoming = outcomes[index]!.parse_result?.typed_fields;
    const oldKey = saleKey(row.raw_payload_json);
    if (row.validation_status !== "COMMITTED" || row.committed_table !== "transactions" ||
        !row.committed_record_id || oldKey === null || oldKey !== saleKey(incoming)) {
      throw new SalesCsvImportError("Recovery stopped: the previous rows do not match a committed prefix of this exact CSV. Review the existing import before proceeding.");
    }
    const old = row.raw_payload_json as Record<string, unknown>;
    // Check audit identifiers too. Sales numeric/date representations were compared above.
    for (const field of ["invoice_id", "order_id", "email", "phone", "competitor_name", "sale_id", "source_system"]) {
      if (old[field] !== undefined && old[field] !== null &&
          String(old[field]).trim() !== String(incoming?.[field] ?? "").trim()) {
        throw new SalesCsvImportError("Recovery stopped: the previous row identifiers differ from this CSV.");
      }
    }
  }
}
