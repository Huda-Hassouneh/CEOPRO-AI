import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";
import { safeUploadName } from "../types/dataconnection.validation.js";
import { MAX_UPLOAD_SIZE_BYTES } from "../types/dataconnection.validation.js";

const rowOutcomeSchema = z
  .object({
    row_index: z.number().int().nonnegative(),
    mode: z.string(),
    parse_result: z
      .object({
        typed_fields: z.record(z.string(), z.unknown())
      })
      .passthrough()
      .nullable()
      .optional(),
    field_errors: z
      .union([z.array(z.unknown()), z.record(z.string(), z.unknown())])
      .default([]),
    error: z.string().nullable().optional()
  })
  .passthrough();

export const extractionResponseSchema = z.object({
  file_name: z.string().min(1),
  detected_type: z.string(),
  headers: z.array(z.string()),
  rows_processed: z.number().int().nonnegative(),
  // The live extraction Space returns this as a boolean flag (despite the
  // plural field name). Accept a numeric count too for older Space revisions.
  rows_truncated_to_limit: z.union([
    z.boolean(),
    z.number().int().nonnegative()
  ]),
  staged_row_count: z.number().int().nonnegative(),
  summary: z.object({
    template_mode: z.string(),
    header_coverage_ratio: z.number().finite().min(0).max(1),
    rows_processed: z.number().int().nonnegative(),
    rows_partial: z.number().int().nonnegative(),
    rows_failed: z.number().int().nonnegative(),
    total_fields_expected: z.number().int().nonnegative(),
    total_fields_extracted: z.number().int().nonnegative(),
    row_outcomes: z.array(rowOutcomeSchema)
  })
});

export type AiExtractionResponse = z.infer<typeof extractionResponseSchema>;

export { isAiIntegrationError as isAiServiceError };

export async function uploadExtractionFile(
  input: {
    file: {
      originalname: string;
      buffer: Buffer;
    };
    countryCode?: string;
    currency?: string;
    timeoutMs?: number;
  },
  client: GradioClient = gradioClient
): Promise<AiExtractionResponse> {
  if (!Buffer.isBuffer(input.file.buffer) || input.file.buffer.length === 0) {
    throw createAiIntegrationError(
      "Extraction requires a non-empty file buffer.",
      "configuration"
    );
  }
  if (input.file.buffer.length > MAX_UPLOAD_SIZE_BYTES) {
    throw createAiIntegrationError(
      "Extraction file exceeds the configured upload size limit.",
      "configuration"
    );
  }

  const fileName = safeUploadName(input.file.originalname);
  const payload = await client.call({
    service: "analytics",
    apiName: "extract_file",
    data: [
      fileName,
      input.file.buffer.toString("base64"),
      input.countryCode ?? "JO",
      input.currency ?? "JOD"
    ],
    timeoutMs: input.timeoutMs
  });
  const parsed = extractionResponseSchema.safeParse(payload);

  if (!parsed.success) {
    // Keep response values out of logs/errors (the payload may contain
    // extracted business data), but expose the failing schema paths so a
    // provider contract drift can be diagnosed from the application log.
    const invalidFields = parsed.error.issues.slice(0, 10).map((issue) => {
      const path = issue.path.map(String).join(".") || "<root>";
      return `${path} (${issue.code})`;
    });
    const issueSuffix = invalidFields.length
      ? ` Invalid fields: ${invalidFields.join(", ")}.`
      : "";
    throw createAiIntegrationError(
      `Gradio extraction response did not match the documented output schema.${issueSuffix}`,
      "malformed_response"
    );
  }
  return parsed.data;
}
