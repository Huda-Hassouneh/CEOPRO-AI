// import { dataManagementRepo } from "../repo/dataconnection.repo.js";

import {
  FeatureUsageCapacityError,
  FeatureUsageUnavailableError,
  getRemainingUsage
} from "../../features/repo/usage.repo.js";
import { createHash, randomUUID } from "node:crypto";
import { extname } from "node:path";
import { uploadExtractionFile } from "../client/ingestion.client.js";
import { validateExtractionResultForDataConnection } from "../validators/extraction-result.validation.js";
import { extractCompleteSalesFile, SalesCsvImportError } from "./sales-csv-import.js";

import {
  validateCreateDataSource,
  validateExtractionUpload,
  safeUploadName
} from "../types/dataconnection.validation.js";

import type {
  CreateDataSourceInput,
  DataSourceResponse,
  ExtractionResult,
  ExtractionUploadInput,
  JsonObject
} from "../types/dataconnection.types.js";
import {
  ConnectedSourceCapacityError,
  BUSINESS_FILE_EXTRACTION_LEASE_MS,
  DataSourceNotFoundError,
  DataSourceReconnectRequiredError,
  DuplicateDataSourceError,
  IngestionJobNotFoundError,
  IngestionJobNotRetryableError,
  dataManagementRepo
} from "../repo/dataconnection.repo.js";
import {
  confirmBusinessImport,
  createBusinessImportPreview,
  DuplicateStructuredImportError,
  persistStructuredBusinessImport,
  reviewBusinessImport,
  type Choice
} from "../repo/structured-business-import.repo.js";
import {
  StructuredImportError,
  parseStructuredBusinessFile,
  type StructuredImportKind
} from "./structured-business-import.js";
import { MAX_UPLOAD_SIZE_BYTES } from "../types/dataconnection.validation.js";

export type DataConnectionServiceError = Error & {
  name: "DataConnectionServiceError";
  code:
    | "INVALID_FILE_UPLOAD"
    | "FILE_SIZE_LIMIT_EXCEEDED"
    | "FEATURE_NOT_INCLUDED"
    | "USAGE_EXCEEDED"
    | "INVALID_PARAMETER"
    | "DUPLICATE_RESOURCE"
    | "SOURCE_RECONNECT_REQUIRED"
    | "RESOURCE_NOT_FOUND"
    | "JOB_NOT_RETRYABLE";
  detail?: unknown;
};

function createServiceError(
  code: DataConnectionServiceError["code"],
  message: string,
  detail?: unknown
): DataConnectionServiceError {
  const error = new Error(message) as DataConnectionServiceError;

  error.name = "DataConnectionServiceError";
  error.code = code;
  error.detail = detail;

  return error;
}

export function isDataConnectionServiceError(
  error: unknown
): error is DataConnectionServiceError {
  return error instanceof Error && error.name === "DataConnectionServiceError";
}

function logSalesUploadFailure(stage: string, error: unknown): void {
  const record = (input: unknown): Record<string, unknown> =>
    input && typeof input === "object" ? input as Record<string, unknown> : {};
  const value = record(error);
  const driverCause = record(record(record(value.meta).driverAdapterError).cause);
  const code = typeof value.code === "string" && /^[A-Za-z0-9_]{1,16}$/.test(value.code)
    ? value.code
    : undefined;
  const kind = typeof value.kind === "string" && /^[a-z_]{1,32}$/.test(value.kind)
    ? value.kind
    : undefined;
  const driverCode = typeof driverCause.originalCode === "string" && /^[A-Za-z0-9_]{1,16}$/.test(driverCause.originalCode)
    ? driverCause.originalCode
    : undefined;
  const driverKind = typeof driverCause.kind === "string" && /^[A-Za-z0-9_]{1,48}$/.test(driverCause.kind)
    ? driverCause.kind
    : undefined;
  // Never log the file, extracted rows, SQL, URL, tenant ID, or exception
  // metadata: Prisma and provider messages can contain business data.
  console.error("[DataConnectionService] Sales upload failed", {
    stage,
    name: error instanceof Error ? error.name : "UnknownError",
    ...(code ? { code } : {}),
    ...(kind ? { kind } : {}),
    ...(driverCode ? { driverCode } : {}),
    ...(driverKind ? { driverKind } : {})
  });
}

function containsCredentialField(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsCredentialField);
  if (typeof value !== "object" || value === null) return false;
  return Object.entries(value).some(([key, nested]) => {
    const normalized = key.toLowerCase().replace(/[\s-]+/g, "_");
    return (
      /^(password|passwd|secret|token|credential|credentials|client_secret|clientsecret|client_credentials|clientcredentials|api_key|apikey|access_token|accesstoken|refresh_token|refreshtoken|authorization|private_key|privatekey|connection_string|connectionstring)$/.test(
        normalized
      ) || containsCredentialField(nested)
    );
  });
}

function getConnectionStatus(
  value: unknown
): DataSourceResponse["connectionStatus"] {
  return value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (value as Record<string, unknown>).ceopro_connection_status ===
      "disconnected"
    ? "disconnected"
    : "configured";
}

// export async function

function validateImportChoices(input: { kind: string; draftId: string; choices: unknown }): Record<string, Choice> {
  if ((input.kind !== "invoices" && input.kind !== "inventory") ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.draftId) ||
    !input.choices || typeof input.choices !== "object" || Array.isArray(input.choices) ||
    Object.keys(input.choices).length > 1000) {
    throw createServiceError("INVALID_PARAMETER", "Invalid import review or confirmation.");
  }
  const choices = input.choices as Record<string, Record<string, unknown>>;
  for (const [key, choice] of Object.entries(choices)) {
    if (!/^(?:Inventory|Invoice Items|[^:]{1,40}):\d{1,5}$/.test(key) ||
      !choice || typeof choice !== "object" || Array.isArray(choice) ||
      (choice.action === "select" && (typeof choice.productId !== "string" || Object.keys(choice).some((field) => !["action", "productId"].includes(field)))) ||
      (choice.action === "create" && (typeof choice.price !== "string" || typeof choice.currency !== "string" ||
        (choice.sku !== undefined && typeof choice.sku !== "string") ||
        Object.keys(choice).some((field) => !["action", "price", "currency", "sku"].includes(field)))) ||
      !["select", "create"].includes(String(choice.action))) {
      throw createServiceError("INVALID_PARAMETER", "Invalid product selection or creation details.");
    }
  }
  return choices as Record<string, Choice>;
}

export const dataConnectionService = {
  reviewStructuredBusinessFile: async (input: {
    tenantId: string; userId: string; kind: string; draftId: string; choices: unknown;
  }) => {
    const choices = validateImportChoices(input);
    try {
      return await reviewBusinessImport({ ...input, kind: input.kind as StructuredImportKind, choices });
    } catch (error) {
      if (error instanceof StructuredImportError) throw createServiceError("INVALID_FILE_UPLOAD", error.message, { message: error.message, issues: error.issues });
      if (error instanceof FeatureUsageUnavailableError) throw createServiceError("FEATURE_NOT_INCLUDED", "Product creation is unavailable for this subscription.");
      throw error;
    }
  },
  previewStructuredBusinessFile: async (input: ExtractionUploadInput, kind: string) => {
    if (kind !== "invoices" && kind !== "inventory") {
      throw createServiceError("INVALID_PARAMETER", "Choose invoices or inventory.");
    }
    let parsed;
    try {
      parsed = parseStructuredBusinessFile(kind, input.file);
    } catch (error) {
      if (error instanceof StructuredImportError) {
        throw createServiceError("INVALID_FILE_UPLOAD", error.message, { message: error.message, issues: error.issues });
      }
      throw error;
    }
    return createBusinessImportPreview({
      tenantId: input.tenantId, userId: input.userId,
      fileName: input.file.originalname, fileBuffer: input.file.buffer, parsed
    });
  },
  confirmStructuredBusinessFile: async (input: {
    tenantId: string; userId: string; kind: string; draftId: string; choices: unknown; reviewHash: unknown;
  }) => {
    const choices = validateImportChoices(input);
    if (typeof input.reviewHash !== "string" || !/^[0-9a-f]{64}$/.test(input.reviewHash)) {
      throw createServiceError("INVALID_PARAMETER", "Review the changes before confirming.");
    }
    try {
      return await confirmBusinessImport({ ...input, kind: input.kind as StructuredImportKind, choices, reviewHash: input.reviewHash });
    } catch (error) {
      if (error instanceof StructuredImportError) {
        throw createServiceError("INVALID_FILE_UPLOAD", error.message, { message: error.message, issues: error.issues });
      }
      if (error instanceof DuplicateStructuredImportError) throw createServiceError("DUPLICATE_RESOURCE", error.message);
      if (error instanceof FeatureUsageUnavailableError) throw createServiceError("FEATURE_NOT_INCLUDED", "Document extraction is unavailable for this subscription.");
      if (error instanceof FeatureUsageCapacityError) throw createServiceError("USAGE_EXCEEDED", "The file exceeds the remaining document extraction allowance.", error.capacity);
      throw error;
    }
  },
  importStructuredBusinessFile: async (
    input: ExtractionUploadInput,
    kind: string
  ) => {
    if (kind !== "invoices" && kind !== "inventory") {
      throw createServiceError("INVALID_PARAMETER", "Import kind must be invoices or inventory.");
    }
    if (input.file.size > MAX_UPLOAD_SIZE_BYTES) {
      throw createServiceError("FILE_SIZE_LIMIT_EXCEEDED", "The file exceeds the configured upload size limit.");
    }
    if (![".csv", ".xlsx"].includes(extname(input.file.originalname).toLowerCase())) {
      throw createServiceError("INVALID_FILE_UPLOAD", "Use the published CSV or XLSX import template.");
    }
    let parsed;
    try {
      parsed = parseStructuredBusinessFile(kind as StructuredImportKind, input.file);
    } catch (error) {
      if (error instanceof StructuredImportError) {
        throw createServiceError("INVALID_FILE_UPLOAD", error.message, { message: error.message, issues: error.issues });
      }
      throw error;
    }
    try {
      return await persistStructuredBusinessImport({
        tenantId: input.tenantId,
        userId: input.userId,
        fileName: input.file.originalname,
        fileBuffer: input.file.buffer,
        parsed
      });
    } catch (error) {
      if (error instanceof StructuredImportError) {
        throw createServiceError("INVALID_FILE_UPLOAD", error.message, { message: error.message, issues: error.issues });
      }
      if (error instanceof DuplicateStructuredImportError) {
        throw createServiceError("DUPLICATE_RESOURCE", error.message);
      }
      if (error instanceof FeatureUsageUnavailableError) {
        throw createServiceError("FEATURE_NOT_INCLUDED", "Document extraction is unavailable for this subscription.");
      }
      if (error instanceof FeatureUsageCapacityError) {
        throw createServiceError("USAGE_EXCEEDED", "The file exceeds the remaining document extraction allowance.", error.capacity);
      }
      throw error;
    }
  },
  getDataConnectionsOverview: async (tenantId: string, userId: string) => {
    const data = await dataManagementRepo.getDataConnectionsOverview(
      tenantId,
      userId
    );

    if (!data) throw new Error("Failed to load data connections overview");
    return data;
  },
  listIngestionJobs: async (tenantId: string, userId: string) =>
    dataManagementRepo.listIngestionJobs(tenantId, userId),
  getIngestionJob: async (tenantId: string, userId: string, jobId: string) => {
    try {
      return await dataManagementRepo.getIngestionJob(tenantId, userId, jobId);
    } catch (error) {
      if (error instanceof IngestionJobNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      throw error;
    }
  },
  getIngestionStagingRows: async (
    tenantId: string,
    userId: string,
    jobId: string,
    page: number,
    pageSize: number
  ) => {
    try {
      return await dataManagementRepo.getIngestionStagingRows(
        tenantId,
        userId,
        jobId,
        page,
        pageSize
      );
    } catch (error) {
      if (error instanceof IngestionJobNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      throw error;
    }
  },
  updateIngestionStagingRow: async (input: {
    tenantId: string;
    userId: string;
    jobId: string;
    rowId: string;
    payload: unknown;
  }) => {
    if (
      typeof input.payload !== "object" ||
      input.payload === null ||
      Array.isArray(input.payload)
    ) {
      throw createServiceError(
        "INVALID_PARAMETER",
        "A corrected staging row must be a JSON object."
      );
    }
    const serialized = JSON.stringify(input.payload);
    if (!serialized || serialized.length > 100_000) {
      throw createServiceError(
        "INVALID_PARAMETER",
        "Corrected staging row data must be smaller than 100 KB."
      );
    }
    if (containsCredentialField(input.payload)) {
      throw createServiceError(
        "INVALID_PARAMETER",
        "Credentials and secrets cannot be stored in imported business rows."
      );
    }
    try {
      return await dataManagementRepo.updateIngestionStagingRow({
        ...input,
        payload: input.payload as Record<string, unknown>
      });
    } catch (error) {
      if (error instanceof IngestionJobNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      if (error instanceof IngestionJobNotRetryableError) {
        throw createServiceError("JOB_NOT_RETRYABLE", error.message);
      }
      throw error;
    }
  },
  retryIngestionJob: async (
    tenantId: string,
    userId: string,
    jobId: string
  ) => {
    try {
      return await dataManagementRepo.retryIngestionJob(
        tenantId,
        userId,
        jobId
      );
    } catch (error) {
      if (error instanceof IngestionJobNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      if (error instanceof IngestionJobNotRetryableError) {
        throw createServiceError("JOB_NOT_RETRYABLE", error.message);
      }
      throw error;
    }
  },
  uploadExtraction: async (
    input: ExtractionUploadInput
  ): Promise<ExtractionResult> => {
    const validationError = validateExtractionUpload(input.file);

    if (validationError === "MISSING_FILE") {
      throw createServiceError(
        "INVALID_FILE_UPLOAD",
        "A multipart file upload is required."
      );
    }

    if (validationError === "INVALID_EXTENSION") {
      throw createServiceError(
        "INVALID_FILE_UPLOAD",
        "Allowed file extensions are .csv, .xlsx, .xlsm, and .pdf."
      );
    }

    if (validationError === "INVALID_SIZE") {
      throw createServiceError(
        "INVALID_FILE_UPLOAD",
        "The uploaded file is empty or has an invalid size."
      );
    }

    if (validationError === "FILE_TOO_LARGE") {
      throw createServiceError(
        "FILE_SIZE_LIMIT_EXCEEDED",
        "File exceeds the configured upload size limit."
      );
    }

    if (validationError === "CONTENT_EXTENSION_MISMATCH") {
      throw createServiceError(
        "INVALID_FILE_UPLOAD",
        "The file content does not match its extension, or the file is malformed. Allowed files are valid .csv, .xlsx, .xlsm, or .pdf documents."
      );
    }

    if (validationError === "TEMPLATE_MISMATCH") {
      throw createServiceError(
        "INVALID_FILE_UPLOAD",
        "The file does not match the KEEL sales template. Use the required product_name, quantity, unit_price, currency, and transaction_date columns."
      );
    }

    const kbUsed = Math.max(1, Math.ceil(input.file.size / 1024));
    const fileName = safeUploadName(input.file.originalname);
    const contentSha256 = createHash("sha256")
      .update(input.file.buffer)
      .digest("hex");
    let completeCsv: Awaited<ReturnType<typeof uploadExtractionFile>> | null = null;
    if ([".csv", ".xlsx", ".xlsm"].includes(extname(fileName).toLowerCase())) {
      try {
        completeCsv = extractCompleteSalesFile(fileName, input.file.buffer);
      } catch (error) {
        if (error instanceof SalesCsvImportError) throw createServiceError("INVALID_FILE_UPLOAD", error.message);
        throw error;
      }
    }
    let existingImport: Awaited<ReturnType<typeof dataManagementRepo.findBusinessFileImportByHash>>;
    try {
      existingImport = await dataManagementRepo.findBusinessFileImportByHash(
        input.tenantId,
        input.userId,
        contentSha256
      );
    } catch (error) {
      logSalesUploadFailure("duplicate_lookup", error);
      throw error;
    }
    const duplicateResult = (existing: {
      jobId: string;
      status: string;
      rowsProcessed: number;
      rowsFailed: number;
      rowsPartial: number;
      stagedRowCount: number;
      config?: Record<string, unknown>;
    }): ExtractionResult => ({
      job_id: existing.jobId,
      job_id_source: "ceopro",
      file_name: fileName,
      detected_type: "existing_import",
      headers: [],
      rows_processed: existing.rowsProcessed,
      rows_partial: existing.rowsPartial,
      rows_failed: existing.rowsFailed,
      rows_truncated_to_limit: (existing.config?.rows_truncated_to_limit as boolean | number | undefined) ?? false,
      source_rows_total: completeCsv?.summary.row_outcomes.length ?? null,
      import_complete: completeCsv ? existing.stagedRowCount === completeCsv.summary.row_outcomes.length : null,
      staged_row_count: existing.stagedRowCount,
      template_mode: "DUPLICATE_UPLOAD",
      is_template_compliant: null,
      data_loss_pct: null,
      header_coverage_ratio: 0,
      row_outcomes: [],
      promotion: null,
      currency_resolution: null,
      duplicate: true,
      job_status: existing.status
    });
    const isExtractionRetry =
      existingImport?.status === "failed" &&
      existingImport.stagedRowCount === 0 &&
      existingImport.config.last_failure_phase === "extraction";
    const staleExtractionReservation =
      existingImport?.status === "extracting" &&
      existingImport.stagedRowCount === 0 &&
      (!existingImport.extractionLeaseAt ||
        Date.now() - existingImport.extractionLeaseAt.getTime() >
          BUSINESS_FILE_EXTRACTION_LEASE_MS);
    if (existingImport && !isExtractionRetry && !staleExtractionReservation) {
      if (completeCsv && existingImport.stagedRowCount < completeCsv.summary.row_outcomes.length) {
        try {
          const recovered = await dataManagementRepo.completeBusinessCsvImport({
            tenantId: input.tenantId, userId: input.userId, sourceId: existingImport.sourceId,
            jobId: existingImport.jobId, contentSha256, rowOutcomes: completeCsv.summary.row_outcomes
          });
          return { ...duplicateResult(existingImport), duplicate: !recovered.recovered,
            recovered: recovered.recovered, added_row_count: recovered.addedRowCount,
            staged_row_count: recovered.stagedRowCount, job_status: recovered.status,
            rows_truncated_to_limit: false, import_complete: true };
        } catch (error) {
          if (error instanceof SalesCsvImportError) throw createServiceError("INVALID_FILE_UPLOAD", error.message);
          if (error instanceof IngestionJobNotRetryableError) throw createServiceError("JOB_NOT_RETRYABLE", error.message);
          throw error;
        }
      }
      if (completeCsv && existingImport.stagedRowCount > completeCsv.summary.row_outcomes.length) {
        throw createServiceError("INVALID_FILE_UPLOAD", "The existing import has more staged records than this exact CSV. Review it before proceeding.");
      }
      return duplicateResult(existingImport);
    }

    let usage: Awaited<ReturnType<typeof getRemainingUsage>>;
    try {
      usage = await getRemainingUsage(
        input.tenantId,
        "document_extraction"
      );
    } catch (error) {
      logSalesUploadFailure("quota_check", error);
      throw error;
    }

    if (!usage) {
      throw createServiceError(
        "FEATURE_NOT_INCLUDED",
        "Document extraction is not available for this subscription."
      );
    }

    const noRemainingQuota =
      usage.remaining !== null && Number(usage.remaining) <= 0;

    if (usage.isExceeded || noRemainingQuota) {
      throw createServiceError(
        "USAGE_EXCEEDED",
        "Document extraction quota has been reached.",
        {
          current_usage: usage.currentUsage,
          limit: usage.limit,
          remaining: 0
        }
      );
    }

    if (usage.remaining !== null && kbUsed > Number(usage.remaining)) {
      throw createServiceError(
        "USAGE_EXCEEDED",
        "This upload exceeds the remaining document extraction quota.",
        {
          requested: kbUsed,
          remaining: usage.remaining,
          unit: "KB"
        }
      );
    }

    let reserved: Awaited<
      ReturnType<typeof dataManagementRepo.reserveBusinessFileImport>
    >;
    try {
      reserved = await dataManagementRepo.reserveBusinessFileImport({
        tenantId: input.tenantId,
        userId: input.userId,
        jobId: randomUUID(),
        contentSha256,
        fileName,
        mimeType: input.file.mimetype,
        fileSizeBytes: input.file.size,
        extractionUsageKb: kbUsed
      });
    } catch (error) {
      if (error instanceof FeatureUsageUnavailableError) {
        throw createServiceError(
          "FEATURE_NOT_INCLUDED",
          "Document extraction is not available for this subscription."
        );
      }
      if (error instanceof FeatureUsageCapacityError) {
        throw createServiceError(
          "USAGE_EXCEEDED",
          "Document extraction quota has been reached.",
          {
            feature_code: error.capacity.featureCode,
            current_usage: error.capacity.currentUsage,
            limit: error.capacity.limit,
            remaining: error.capacity.remaining,
            requested: error.capacity.requested,
            unit: "KB"
          }
        );
      }
      logSalesUploadFailure("reserve_import", error);
      throw error;
    }
    if (reserved.duplicate) return duplicateResult(reserved);

    let data: Awaited<ReturnType<typeof uploadExtractionFile>>;
    let persisted: Awaited<
      ReturnType<typeof dataManagementRepo.recordBusinessFileIngestion>
    >;
    let stage = "ai_extraction";
    try {
      data = completeCsv ?? await uploadExtractionFile({
        file: {
          originalname: fileName,
          buffer: input.file.buffer
        }
      });

      stage = "extraction_validation";
      const extractionValidationError =
        validateExtractionResultForDataConnection(data);
      if (extractionValidationError) {
        throw createServiceError(
          "INVALID_FILE_UPLOAD",
          extractionValidationError
        );
      }

      // The Gradio contract returns extracted rows, not a KEEL job ID or a
      // storage key. KEEL creates and owns its local ingestion job.
      stage = "stage_sales_rows";
      persisted = await dataManagementRepo.recordBusinessFileIngestion({
        tenantId: input.tenantId,
        userId: input.userId,
        sourceId: reserved.sourceId,
        jobId: reserved.jobId,
        contentSha256,
        fileName,
        mimeType: input.file.mimetype,
        fileSizeBytes: input.file.size,
        detectedType: data.detected_type,
        headerCoverageRatio: data.summary.header_coverage_ratio,
        rowsTruncatedToLimit: data.rows_truncated_to_limit,
        sourceRowsTotal: completeCsv?.summary.row_outcomes.length,
        extractionMethod: completeCsv ? (extname(fileName).toLowerCase() === ".csv" ? "canonical_csv" : "canonical_file") : "ai",
        rowOutcomes: data.summary.row_outcomes
      });
    } catch (error) {
      logSalesUploadFailure(stage, error);
      try {
        await dataManagementRepo.markBusinessFileExtractionFailed({
          tenantId: input.tenantId,
          userId: input.userId,
          sourceId: reserved.sourceId,
          jobId: reserved.jobId
        });
      } catch {
        console.error(
          "[DataConnections] Failed to release a document extraction reservation."
        );
      }
      throw error;
    }

    return {
      job_id: reserved.jobId,
      job_id_source: "ceopro",
      file_name: fileName,
      detected_type: data.detected_type,
      headers: data.headers,
      rows_processed: data.summary.rows_processed,
      rows_partial: data.summary.rows_partial,
      rows_failed: data.summary.rows_failed,
      rows_truncated_to_limit: data.rows_truncated_to_limit,
      source_rows_total: completeCsv?.summary.row_outcomes.length ?? null,
      import_complete: completeCsv ? true : null,
      added_row_count: persisted.stagedRowCount,
      staged_row_count: persisted.stagedRowCount,
      template_mode: data.summary.template_mode,
      is_template_compliant: null,
      data_loss_pct: null,
      header_coverage_ratio: data.summary.header_coverage_ratio,
      row_outcomes: data.summary.row_outcomes,
      promotion: null,
      currency_resolution: null,
      duplicate: false,
      job_status: "queued"
    };
  },
  createDataSource: async (
    input: CreateDataSourceInput
  ): Promise<DataSourceResponse> => {
    const validation = validateCreateDataSource(input.payload);

    if (!validation.success) {
      throw createServiceError("INVALID_PARAMETER", validation.message);
    }

    let source: Awaited<
      ReturnType<typeof dataManagementRepo.createPersistentSource>
    >;
    try {
      source = await dataManagementRepo.createPersistentSource({
        tenantId: input.tenantId,
        userId: input.userId,
        name: validation.data.name,
        sourceType: validation.data.sourceType,
        syncFrequencyMinutes: validation.data.syncFrequencyMinutes ?? 1440,
        sourceUrl: validation.data.sourceUrl,
        metadata: validation.data.metadata ?? {}
      });
    } catch (error) {
      if (error instanceof ConnectedSourceCapacityError) {
        if (!error.featureIncluded) {
          throw createServiceError(
            "FEATURE_NOT_INCLUDED",
            error.message
          );
        }
        throw createServiceError(
          "USAGE_EXCEEDED",
          error.message,
          {
            feature_code: "connected_data_sources",
            ...error.capacity,
            requested: 1,
            unit: "sources"
          }
        );
      }
      if (error instanceof DuplicateDataSourceError) {
        throw createServiceError(
          "DUPLICATE_RESOURCE",
          error.message
        );
      }
      throw error;
    }

    return {
      id: source.source_id,

      name: source.source_name,

      sourceType: source.source_type,
      sourceUrl: source.source_url,
      connectionStatus: getConnectionStatus(source.collector_config),

      isActive: source.is_active,

      syncFrequencyMinutes: source.sync_frequency_minutes,

      lastSyncedAt: source.last_synced_at
        ? source.last_synced_at.toISOString()
        : null,

      createdAt: source.created_at ? source.created_at.toISOString() : null,

      metadata: (source.collector_config &&
      typeof source.collector_config === "object" &&
      !Array.isArray(source.collector_config)
        ? source.collector_config
        : {}) as JsonObject
    };
  },

  setPersistentSourceActive: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
    isActive: boolean;
  }): Promise<DataSourceResponse> => {
    let source: Awaited<
      ReturnType<typeof dataManagementRepo.setPersistentSourceActive>
    >;
    try {
      source = await dataManagementRepo.setPersistentSourceActive(input);
    } catch (error) {
      if (error instanceof DataSourceNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      if (error instanceof DataSourceReconnectRequiredError) {
        throw createServiceError("SOURCE_RECONNECT_REQUIRED", error.message);
      }
      if (error instanceof ConnectedSourceCapacityError) {
        if (!error.featureIncluded) {
          throw createServiceError("FEATURE_NOT_INCLUDED", error.message);
        }
        throw createServiceError("USAGE_EXCEEDED", error.message, {
          feature_code: "connected_data_sources",
          ...error.capacity,
          requested: 1,
          unit: "sources"
        });
      }
      throw error;
    }

    return {
      id: source.source_id,
      name: source.source_name,
      sourceType: source.source_type,
      sourceUrl: source.source_url,
      connectionStatus: getConnectionStatus(source.collector_config),
      isActive: source.is_active,
      syncFrequencyMinutes: source.sync_frequency_minutes,
      lastSyncedAt: source.last_synced_at?.toISOString() ?? null,
      createdAt: source.created_at?.toISOString() ?? null,
      metadata: (
        source.collector_config &&
        typeof source.collector_config === "object" &&
        !Array.isArray(source.collector_config)
          ? source.collector_config
          : {}
      ) as JsonObject
    };
  },

  disconnectPersistentSource: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
  }): Promise<DataSourceResponse> => {
    let source: Awaited<
      ReturnType<typeof dataManagementRepo.disconnectPersistentSource>
    >;
    try {
      source = await dataManagementRepo.disconnectPersistentSource(input);
    } catch (error) {
      if (error instanceof DataSourceNotFoundError) {
        throw createServiceError("RESOURCE_NOT_FOUND", error.message);
      }
      throw error;
    }

    return {
      id: source.source_id,
      name: source.source_name,
      sourceType: source.source_type,
      sourceUrl: source.source_url,
      connectionStatus: "disconnected",
      isActive: source.is_active,
      syncFrequencyMinutes: source.sync_frequency_minutes,
      lastSyncedAt: source.last_synced_at?.toISOString() ?? null,
      createdAt: source.created_at?.toISOString() ?? null,
      metadata: (
        source.collector_config &&
        typeof source.collector_config === "object" &&
        !Array.isArray(source.collector_config)
          ? source.collector_config
          : {}
      ) as JsonObject
    };
  }
};
