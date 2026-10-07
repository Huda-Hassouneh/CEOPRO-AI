import type { AiExtractionResponse } from "../client/ingestion.client.js";
import {
  assessExtractionHeaders,
  REQUIRED_CANONICAL_TEMPLATE_FIELDS
} from "./extraction-template.validation.js";

function hasErrors(value: unknown[] | Record<string, unknown>): boolean {
  return Array.isArray(value) ? value.length > 0 : Object.keys(value).length > 0;
}

function hasUsableValue(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "string" || value.trim() === "") return false;
  return Number.isFinite(Number(value));
}

/**
 * Enforces the extraction contract before the Data Connection service
 * creates a source, ingestion job, staging rows, or consumes quota.
 */
export function validateExtractionResultForDataConnection(
  result: AiExtractionResponse
): string | null {
  const assessment = assessExtractionHeaders(result.headers);
  if (assessment.mode !== "TEMPLATE_COMPLIANT") {
    return "The file headers do not match the required CEOPRO sales template.";
  }

  if (result.summary.template_mode !== "TEMPLATE_COMPLIANT") {
    return "The extraction service did not confirm the required CEOPRO sales template.";
  }

  if (result.summary.rows_processed < 1 || result.summary.row_outcomes.length < 1) {
    return "The file contains no extractable sales-data rows.";
  }

  if (
    result.summary.rows_partial > 0 ||
    result.summary.rows_failed > 0 ||
    result.summary.row_outcomes.length !== result.summary.rows_processed + result.summary.rows_failed
  ) {
    return "One or more rows failed sales-data validation. Correct the file and upload it again.";
  }

  for (const outcome of result.summary.row_outcomes) {
    if (outcome.mode !== "TEMPLATE_COMPLIANT") {
      return "At least one row was not parsed using the required CEOPRO sales template.";
    }
    if (outcome.error || hasErrors(outcome.field_errors)) {
      return "One or more rows contain invalid sales-field values. Correct the file and upload it again.";
    }

    const typedFields = outcome.parse_result?.typed_fields;
    if (!typedFields) {
      return "The extraction service returned a row without structured sales fields.";
    }

    for (const field of REQUIRED_CANONICAL_TEMPLATE_FIELDS) {
      const value = typedFields[field];
      if (field === "product_name" || field === "currency" || field === "transaction_date") {
        if (typeof value !== "string" || value.trim() === "") {
          return `A row is missing the required ${field} field.`;
        }
      } else if (!hasUsableValue(value)) {
        return `A row is missing a valid ${field} field.`;
      }
    }
  }

  return null;
}
