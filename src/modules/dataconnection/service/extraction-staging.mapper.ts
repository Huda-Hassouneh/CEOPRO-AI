import type { ExtractionRowOutcome } from "../types/dataconnection.types.js";

type StagingValidationStatus = "PENDING" | "PARTIAL" | "INVALID";

export type ExtractionStagingRowInput = {
  tenant_id: string;
  job_id: string;
  raw_payload: Record<string, unknown>;
  validation_status: StagingValidationStatus;
  validation_errors: string | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function fieldErrorMap(
  fieldErrors: unknown[] | Record<string, unknown>,
  rowError: string | null
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (Array.isArray(fieldErrors)) {
    for (const [index, fieldError] of fieldErrors.entries()) {
      const errorRecord = asRecord(fieldError);
      const fieldName =
        typeof errorRecord?.field === "string"
          ? errorRecord.field
          : `field_${index + 1}`;
      const message =
        typeof errorRecord?.message === "string"
          ? errorRecord.message
          : typeof fieldError === "string"
            ? fieldError
            : JSON.stringify(fieldError);
      errors[fieldName] = message ?? "Invalid field value.";
    }
  } else {
    for (const [fieldName, value] of Object.entries(fieldErrors)) {
      errors[fieldName] =
        typeof value === "string"
          ? value
          : JSON.stringify(value) ?? "Invalid field value.";
    }
  }
  if (rowError) errors._row = rowError;
  return errors;
}

export function mapExtractionOutcomeToStagingRow(
  tenantId: string,
  jobId: string,
  outcome: ExtractionRowOutcome
): ExtractionStagingRowInput {
  const rawPayload = outcome.parse_result?.typed_fields ?? {};
  const errors = fieldErrorMap(outcome.field_errors, outcome.error ?? null);
  const hasExtractedFields = Object.keys(rawPayload).length > 0;
  const hasValidationErrors = Object.keys(errors).length > 0;
  const validationStatus: StagingValidationStatus = !hasExtractedFields
    ? "INVALID"
    : hasValidationErrors
      ? "PARTIAL"
      : "PENDING";

  return {
    tenant_id: tenantId,
    job_id: jobId,
    raw_payload: rawPayload,
    validation_status: validationStatus,
    validation_errors: hasValidationErrors
      ? JSON.stringify(errors).slice(0, 20_000)
      : null
  };
}
