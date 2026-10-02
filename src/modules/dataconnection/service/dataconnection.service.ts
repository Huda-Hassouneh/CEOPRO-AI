// import { dataManagementRepo } from "../repo/dataconnection.repo.js";

import {
  assertFeatureCapacity,
  documentsRepo,
  getRemainingUsage,
  incrementUsage
} from "../../features/repo/usage.repo.js";

import {
  uploadExtractionFile,
  processPendingExtraction,
  createAiServiceError
} from "../client/ingestion.client.js";

import {
  validateCreateDataSource,
  validateExtractionUpload
} from "../types/dataconnection.validation.js";

import type {
  CreateDataSourceInput,
  DataSourceResponse,
  ExtractionResult,
  ExtractionUploadInput,
  JsonObject
} from "../types/dataconnection.types.js";
import { dataManagementRepo } from "../repo/dataconnection.repo.js";

export type DataConnectionServiceError = Error & {
  name: "DataConnectionServiceError";
  code:
    | "INVALID_FILE_UPLOAD"
    | "FILE_SIZE_LIMIT_EXCEEDED"
    | "FEATURE_NOT_INCLUDED"
    | "USAGE_EXCEEDED"
    | "INVALID_PARAMETER"
    | "STORAGE_EXCEEDED";
  detail?: any;
};

function createServiceError(
  code: DataConnectionServiceError["code"],
  message: string,
  detail?: any
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

// export async function

export const dataConnectionService = {
  getDataConnectionsOverview: async (tenantId: string) => {
    console.log("accesseds");

    const data = await dataManagementRepo.getDataConnectionsOverview(tenantId);
    console.log({ data });

    if (!data) throw new Error("Failed to load data connections overview");
    return data;
  },
  processPending: async (args: {
    tenantId: string;
    authorization?: string;
    requestedLimit: number;
  }) => {
    const usage = await getRemainingUsage(args.tenantId, "document_extraction");

    if (!usage) {
      throw createServiceError(
        "FEATURE_NOT_INCLUDED",
        "Document extraction is not available for this subscription."
      );
    }

    const allowedLimit =
      usage.remaining === null
        ? args.requestedLimit
        : Math.max(0, Math.min(args.requestedLimit, Number(usage.remaining)));

    if (allowedLimit <= 0) {
      throw createServiceError(
        "USAGE_EXCEEDED",
        "Document extraction quota has been reached."
      );
    }

    return processPendingExtraction({
      limit: allowedLimit,
      authorization: args.authorization
    });
  },
  uploadExtraction: async (
    input: ExtractionUploadInput
  ): Promise<ExtractionResult> => {
    console.log("accessed 2");

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
        "File exceeds the 10 MB size limit."
      );
    }

    const kbUsed = Math.max(1, Math.ceil(input.file.size / 1024));

    const usage = await getRemainingUsage(
      input.tenantId,
      "document_extraction"
    );

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

    const storageMb = input.file.size / 1024 ** 2;

    const storage = await assertFeatureCapacity({
      tenantId: input.tenantId,
      featureCode: "document_storage_mb",
      additionalAmount: storageMb
    });

    if (!storage.allowed) {
      if (storage.reason === "FEATURE_NOT_INCLUDED") {
        throw createServiceError(
          "FEATURE_NOT_INCLUDED",
          "Document storage is not available for this subscription."
        );
      }

      throw createServiceError(
        "STORAGE_EXCEEDED",
        "This upload exceeds the available document storage capacity.",
        {
          feature_code: "document_storage_mb",
          reason: "CAPACITY_REACHED",
          current_usage: storage.entitlement.currentUsage,
          limit: storage.entitlement.limit,
          requested: storageMb,
          remaining: storage.entitlement.remaining,
          unit: "MB"
        }
      );
    }

    const startedAt = new Date();

    const data = await uploadExtractionFile({
      tenantId: input.tenantId,
      file: input.file,
      authorization: input.authorization
    });

    const endedAt = new Date();

    const jobId = typeof data.job_id === "string" ? data.job_id.trim() : "";

    if (!jobId) {
      throw createAiServiceError(
        "AI extraction service response is missing job_id."
      );
    }

    const minioObjectKey =
      typeof data.minio_object_key === "string"
        ? data.minio_object_key.trim()
        : "";

    if (!minioObjectKey) {
      throw createAiServiceError(
        "AI extraction service response is missing minio_object_key."
      );
    }

    const rowsProcessed = Number(data.rows_processed ?? 0);

    const rowsFailed = Number(data.rows_failed ?? 0);

    /*
     * Sales/business-file uploads belong to the Data Connection
     * ingestion domain, not the RAG knowledge-document domain.
     *
     * Persist the AI ingestion result through data_sources +
     * ingestion_jobs so GET /data-connection can expose it through
     * recentImports.
     */
    await dataManagementRepo.recordBusinessFileIngestion({
      tenantId: input.tenantId,
      jobId,

      fileName: input.file.originalname,
      mimeType: input.file.mimetype,
      fileSizeBytes: input.file.size,
      minioObjectKey,

      rowsProcessed:
        Number.isFinite(rowsProcessed) && rowsProcessed >= 0
          ? Math.trunc(rowsProcessed)
          : 0,

      rowsFailed:
        Number.isFinite(rowsFailed) && rowsFailed >= 0
          ? Math.trunc(rowsFailed)
          : 0,

      startedAt,
      endedAt
    });

    await incrementUsage(input.tenantId, "document_extraction", kbUsed);

    return {
      job_id: data.job_id,
      template_mode: data.template_mode,
      is_template_compliant: data.is_template_compliant,
      rows_processed: data.rows_processed,
      rows_partial: data.rows_partial,
      rows_failed: data.rows_failed,
      data_loss_pct: data.data_loss_pct,
      header_coverage_ratio: data.header_coverage_ratio,
      row_outcomes: data.row_outcomes,
      promotion: data.promotion,
      currency_resolution: data.currency_resolution
    };
  },
  createDataSource: async (
    input: CreateDataSourceInput
  ): Promise<DataSourceResponse> => {
    const validation = validateCreateDataSource(input.payload);

    if (!validation.success) {
      throw createServiceError("INVALID_PARAMETER", validation.message);
    }

    /*
     * data_integration is the BOOLEAN capability.
     *
     * This should already be enforced at the route
     * using requireEntitlement("data_integration").
     *
     * connected_data_sources is the numeric capacity
     * and therefore belongs here.
     */
    const capacity = await assertFeatureCapacity({
      tenantId: input.tenantId,
      featureCode: "connected_data_sources",
      additionalAmount: 1
    });

    if (!capacity.allowed) {
      if (capacity.reason === "FEATURE_NOT_INCLUDED") {
        throw createServiceError(
          "FEATURE_NOT_INCLUDED",
          "Connected data sources are not available for this subscription."
        );
      }

      throw createServiceError(
        "USAGE_EXCEEDED",
        "The connected data source limit has been reached.",
        {
          feature_code: "connected_data_sources",
          current_usage: capacity.entitlement.currentUsage,
          limit: capacity.entitlement.limit,
          remaining: capacity.entitlement.remaining,
          requested: 1,
          unit: "sources"
        }
      );
    }

    const source = await dataManagementRepo.createPersistentSource({
      tenantId: input.tenantId,

      name: validation.data.name,

      sourceType: validation.data.sourceType,

      syncFrequencyMinutes: validation.data.syncFrequencyMinutes ?? 1440,

      metadata: validation.data.metadata ?? {}
    });

    return {
      id: source.source_id,

      name: source.source_name,

      sourceType: source.source_type,

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
  }
};
