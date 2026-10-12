import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import { COUNTED_CONNECTED_SOURCE_TYPES } from "../../../constants/data-source-types.js";
import type {
  ExtractionRowOutcome,
  JsonObject
} from "../types/dataconnection.types.js";
import { mapExtractionOutcomeToStagingRow } from "../service/extraction-staging.mapper.js";
import { writeStagingRowsInBatches } from "./staging-batches.js";
import {
  getConnectedDataSourceCapacityInTransaction,
  releaseFeatureUsageInTransaction,
  reserveFeatureUsageInTransaction
} from "../../features/repo/usage.repo.js";

const PERSISTENT_SOURCE_TYPES = COUNTED_CONNECTED_SOURCE_TYPES;
export const BUSINESS_FILE_EXTRACTION_LEASE_MS = 15 * 60 * 1000;
// A large CSV can contain tens of thousands of extracted rows. Keep each
// INSERT below PostgreSQL's bind-parameter limit and give the all-or-nothing
// staging transaction time to write the full file.
const BUSINESS_FILE_STAGING_TRANSACTION_TIMEOUT_MS = 180_000;

export class ConnectedSourceCapacityError extends Error {
  readonly capacity: {
    currentUsage: number;
    limit: number | null;
    remaining: number | null;
    isUnlimited: boolean;
  };
  readonly featureIncluded: boolean;

  constructor(input: {
    message: string;
    featureIncluded: boolean;
    currentUsage: number;
    limit: number | null;
    remaining: number | null;
    isUnlimited: boolean;
  }) {
    super(input.message);
    this.name = "ConnectedSourceCapacityError";
    this.capacity = {
      currentUsage: input.currentUsage,
      limit: input.limit,
      remaining: input.remaining,
      isUnlimited: input.isUnlimited
    };
    this.featureIncluded = input.featureIncluded;
  }
}

export class DuplicateDataSourceError extends Error {
  constructor() {
    super("A source with this provider identity is already registered.");
    this.name = "DuplicateDataSourceError";
  }
}

export class DataSourceNotFoundError extends Error {
  constructor() {
    super("Data source was not found for this tenant.");
    this.name = "DataSourceNotFoundError";
  }
}

export class DataSourceReconnectRequiredError extends Error {
  constructor() {
    super("A disconnected source must be registered again before it can be reactivated.");
    this.name = "DataSourceReconnectRequiredError";
  }
}

export class IngestionJobNotFoundError extends Error {
  constructor() {
    super("Ingestion job was not found for this tenant.");
    this.name = "IngestionJobNotFoundError";
  }
}

export class IngestionJobNotRetryableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "IngestionJobNotRetryableError";
  }
}

function sanitizeJobError(value: string | null | undefined): string | null {
  if (!value) return null;
  return value
    .replace(/postgres(?:ql)?:\/\/\S+/gi, "[redacted-database-url]")
    .replace(/\bBearer\s+[^\s,;]+/gi, "Bearer [redacted]")
    .replace(/\b(password|token|secret|api[_ -]?key)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[redacted-email]")
    .replace(/\s+/g, " ")
    .slice(0, 600);
}

// --- 1. Shared Localization & Formatting Helpers ---

const localized = (en: string, ar: string) => ({ en, ar });

const getCategoriesByType = (type: string) => {
  switch (type.toLowerCase()) {
    case "documents":
    case "businesssystem":
      return [
        localized("Sales", "المبيعات"),
        localized("Products", "المنتجات"),
        localized("Inventory", "المخزون")
      ];
    case "website":
      return [
        localized("Products", "المنتجات"),
        localized("Pricing", "التسعير")
      ];
    case "analytics":
      return [
        localized("Website traffic", "زيارات الموقع"),
        localized("Customer activity", "نشاط العملاء")
      ];
    default:
      return [localized("General Data", "بيانات عامة")];
  }
};

const mapJobStatusToConnectionStatus = (
  dbStatus?: string,
  promotedRows = 0
) => {
  if (!dbStatus) return "configured";

  switch (dbStatus.toUpperCase()) {
    case "QUEUED":
    case "EXTRACTING":
    case "PROCESSING":
      return "processing";
    case "COMPLETED":
      return promotedRows > 0 ? "synced" : "needsAttention";
    case "FAILED":
      return "needsAttention";
    default:
      return "unknown";
  }
};

function hasDisconnectedConnection(config: unknown): boolean {
  return Boolean(
    config &&
      typeof config === "object" &&
      !Array.isArray(config) &&
      (config as Record<string, unknown>).ceopro_connection_status ===
        "disconnected"
  );
}

const mapJobStatusToImportStatus = (dbStatus: string) => {
  const statusMap: Record<string, string> = {
    EXTRACTING: "Processing",
    QUEUED: "Processing",
    PROCESSING: "Processing",
    COMPLETED: "Completed",
    FAILED: "Failed"
  };

  return statusMap[dbStatus.toUpperCase()] || dbStatus;
};

const getActivityType = (sourceType?: string | null) => {
  if (!sourceType) return "Connection";

  switch (sourceType.toLowerCase()) {
    case "documents":
      return "File";
    case "analytics":
      return "Analytics";
    case "website":
      return "Website";
    case "businesssystem":
      return "Business System";
    default:
      return "Connection";
  }
};

// --- 2. Transaction-scoped Tenant Context ---

/**
 * CEOPRO's get_current_tenant() returns NULL unless BOTH
 * app.current_user_id and app.current_tenant_id are set. A Prisma `where`
 * tenant filter alone does not satisfy the RLS policies.
 *
 * set_config(..., true) is LOCAL to this transaction. The callback always
 * uses the same transaction client, so connection-pool reuse cannot leak
 * tenant context into another request.
 *
 * IMPORTANT: Both IDs must come from the authenticated request after
 * requireTenant verifies membership; do not accept arbitrary client IDs.
 * This helper only establishes session context; it does not authorize users.
 */
async function withTenantContext<T>(
  tenantId: string,
  userId: string,
  work: (tx: Prisma.TransactionClient) => Promise<T>
): Promise<T> {
  if (!tenantId?.trim() || !userId?.trim()) {
    throw new Error("Authenticated tenant and user context are required");
  }

  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${tenantId}, true),
        set_config('app.current_user_id', ${userId}, true)
    `;

    return work(tx);
  });
}

/**
 * Used by both the activity endpoint and the overview endpoint, ensuring
 * the overview's two queries share the same RLS-enabled transaction.
 *
 * RAG documents intentionally do not appear in this ingestion-job feed.
 */
async function getRecentActivityInTransaction(
  tx: Prisma.TransactionClient,
  tenantId: string,
  limit: number
) {
  const jobs = await tx.ingestion_jobs.findMany({
    where: { tenant_id: tenantId },
    include: {
      data_sources: {
        select: { source_name: true, source_type: true }
      }
    },
    orderBy: { created_at: "desc" },
    take: limit
  });

  return jobs.map((job) => {
    const sourceName = job.data_sources?.source_name || "Unknown Source";
    const sourceType = job.data_sources?.source_type || "unknown";
    const isBusinessFile = sourceType.toLowerCase() === "documents";

    return {
      id: job.job_id,
      date: job.started_at || job.created_at,
      source: isBusinessFile
        ? localized("Business Data Files", "ملفات بيانات الأعمال")
        : localized(sourceName, sourceName),
      // ingestion_jobs does not store original_file_name. For file imports,
      // the source name is the best persisted display name in this schema.
      name: isBusinessFile ? sourceName : `Sync - ${sourceName}`,
      type: getActivityType(sourceType),
      status: mapJobStatusToImportStatus(job.job_status)
    };
  });
}

// --- 3. Repository Methods ---

export const dataManagementRepo = {
  /**
   * Returns recent ingestion activity for the authenticated tenant.
   * This includes manual file sources even when is_active=false.
   */
  getRecentActivity: async (tenantId: string, userId: string, limit = 10) => {
    return withTenantContext(tenantId, userId, (tx) =>
      getRecentActivityInTransaction(tx, tenantId, limit)
    );
  },

  /** Returns the Data Connection overview with the existing API shape. */
  getDataConnectionsOverview: async (tenantId: string, userId: string) => {
    return withTenantContext(tenantId, userId, async (tx) => {
      const dataSources = await tx.data_sources.findMany({
        where: {
          tenant_id: tenantId,
          source_type: { in: [...PERSISTENT_SOURCE_TYPES] }
        },
        include: {
          ingestion_jobs: {
            orderBy: { created_at: "desc" }
          }
        }
      });
      const promotedRowsByJob = await tx.import_staging_rows.groupBy({
        by: ["job_id"],
        where: {
          tenant_id: tenantId,
          validation_status: "COMMITTED",
          committed_record_id: { not: null },
          committed_table: { not: null }
        },
        _count: { _all: true }
      });
      const promotedCountByJobId = new Map(
        promotedRowsByJob.map((group) => [group.job_id, group._count._all])
      );

      const connectedSources = dataSources.map((source) => {
        const isDisconnected = hasDisconnectedConnection(source.collector_config);
        const latestJob = source.ingestion_jobs[0];
        const promotedRows = source.ingestion_jobs.reduce(
          (sum, job) => sum + (promotedCountByJobId.get(job.job_id) ?? 0),
          0
        );
        const latestJobPromotedRows = latestJob
          ? (promotedCountByJobId.get(latestJob.job_id) ?? 0)
          : 0;
        const latestPromotedJob = source.ingestion_jobs.find(
          (job) =>
            job.job_status.toUpperCase() === "COMPLETED" &&
            (promotedCountByJobId.get(job.job_id) ?? 0) > 0
        );
        const status = mapJobStatusToConnectionStatus(
          latestJob?.job_status,
          latestJobPromotedRows
        );
        const actions = [
          "details",
          ...(isDisconnected
            ? []
            : source.is_active
              ? ["pause", "disconnect"]
              : ["reactivate", "disconnect"])
        ];
        if (!isDisconnected && latestJob?.job_status?.toUpperCase() === "FAILED")
          actions.push("retry");

        return {
          id: source.source_id,
          latestJobId: latestJob?.job_id ?? null,
          latestJobStatus: latestJob?.job_status?.toLowerCase() ?? null,
          type: source.source_type,
          name: localized(source.source_name, source.source_name),
          status: isDisconnected
            ? "disconnected"
            : source.is_active
              ? status
              : "paused",
          isActive: source.is_active,
          sourceUrl: source.source_url,
          lastUpdatedAt: latestPromotedJob?.ended_at?.toISOString() ?? null,
          lastAttemptAt:
            latestJob?.ended_at?.toISOString() ??
            latestJob?.created_at?.toISOString() ??
            null,
          recordCount: promotedRows > 0 ? promotedRows : null,
          categories: getCategoriesByType(source.source_type),
          actions
        };
      });
      const sourceCapacity = await getConnectedDataSourceCapacityInTransaction(
        tx,
        tenantId
      );

      // Deliberately NOT limited to active sources: manual uploads belong
      // in recentImports even though they are not persistent connections.
      const recentImports = await getRecentActivityInTransaction(
        tx,
        tenantId,
        5
      );

      return {
        connectedSources,
        sourceCapacity,
        recentImports,
        availableSourceTypes: [
          "analytics",
          "website",
          "businessSystem",
          "documents"
        ]
      };
    });
  },

  listIngestionJobs: async (tenantId: string, userId: string, limit = 50) => {
    return withTenantContext(tenantId, userId, async (tx) => {
      const jobs = await tx.ingestion_jobs.findMany({
        where: { tenant_id: tenantId },
        orderBy: { created_at: "desc" },
        take: limit,
        select: {
          job_id: true,
          source_id: true,
          job_status: true,
          rows_processed: true,
          rows_failed: true,
          rows_partial: true,
          rows_quarantined: true,
          error_log: true,
          started_at: true,
          ended_at: true,
          created_at: true,
          data_sources: {
            select: { source_name: true, source_type: true }
          }
        }
      });
      return jobs.map((job) => ({
        id: job.job_id,
        sourceId: job.source_id,
        sourceName: job.data_sources.source_name,
        sourceType: job.data_sources.source_type,
        status: job.job_status.toLowerCase(),
        rowsProcessed: job.rows_processed ?? 0,
        rowsFailed: job.rows_failed ?? 0,
        rowsPartial: job.rows_partial ?? 0,
        rowsQuarantined: job.rows_quarantined,
        error: sanitizeJobError(job.error_log),
        startedAt: job.started_at?.toISOString() ?? null,
        endedAt: job.ended_at?.toISOString() ?? null,
        createdAt: job.created_at?.toISOString() ?? null
      }));
    });
  },

  getIngestionJob: async (tenantId: string, userId: string, jobId: string) => {
    return withTenantContext(tenantId, userId, async (tx) => {
      const job = await tx.ingestion_jobs.findFirst({
        where: { tenant_id: tenantId, job_id: jobId },
        select: {
          job_id: true,
          source_id: true,
          job_status: true,
          rows_processed: true,
          rows_failed: true,
          rows_partial: true,
          rows_quarantined: true,
          processing_attempts: true,
          error_log: true,
          started_at: true,
          ended_at: true,
          created_at: true,
          data_sources: {
            select: { source_name: true, source_type: true, source_url: true }
          }
        }
      });
      if (!job) throw new IngestionJobNotFoundError();

      const groups = await tx.import_staging_rows.groupBy({
        by: ["validation_status"],
        where: { tenant_id: tenantId, job_id: jobId },
        _count: { _all: true }
      });
      const rowCounts = Object.fromEntries(
        groups.map((group) => [
          group.validation_status.toLowerCase(),
          group._count._all
        ])
      );

      return {
        id: job.job_id,
        sourceId: job.source_id,
        sourceName: job.data_sources.source_name,
        sourceType: job.data_sources.source_type,
        sourceUrl: job.data_sources.source_url,
        status: job.job_status.toLowerCase(),
        rowsProcessed: job.rows_processed ?? 0,
        rowsFailed: job.rows_failed ?? 0,
        rowsPartial: job.rows_partial ?? 0,
        rowsQuarantined: job.rows_quarantined,
        processingAttempts: job.processing_attempts,
        stagedRows: rowCounts,
        retryable:
          job.job_status.toUpperCase() === "FAILED" &&
          (rowCounts.pending ?? 0) > 0,
        error: sanitizeJobError(job.error_log),
        startedAt: job.started_at?.toISOString() ?? null,
        endedAt: job.ended_at?.toISOString() ?? null,
        createdAt: job.created_at?.toISOString() ?? null
      };
    });
  },

  getIngestionStagingRows: async (
    tenantId: string,
    userId: string,
    jobId: string,
    page: number,
    pageSize: number
  ) => {
    return withTenantContext(tenantId, userId, async (tx) => {
      const job = await tx.ingestion_jobs.findFirst({
        where: { tenant_id: tenantId, job_id: jobId },
        select: { job_id: true }
      });
      if (!job) throw new IngestionJobNotFoundError();

      const [total, rows] = await Promise.all([
        tx.import_staging_rows.count({
          where: { tenant_id: tenantId, job_id: jobId }
        }),
        tx.import_staging_rows.findMany({
          where: { tenant_id: tenantId, job_id: jobId },
          orderBy: { staging_row_id: "asc" },
          skip: (page - 1) * pageSize,
          take: pageSize,
          select: {
            staging_row_id: true,
            raw_payload_json: true,
            validation_status: true,
            validation_errors: true,
            committed_record_id: true,
            committed_table: true,
            created_at: true
          }
        })
      ]);
      return {
        page,
        pageSize,
        total,
        rows: rows.map((row) => ({
          id: row.staging_row_id.toString(),
          payload: row.raw_payload_json,
          status: row.validation_status.toLowerCase(),
          errors: row.validation_errors,
          committedRecordId: row.committed_record_id,
          committedTable: row.committed_table,
          createdAt: row.created_at?.toISOString() ?? null
        }))
      };
    });
  },

  updateIngestionStagingRow: async (input: {
    tenantId: string;
    userId: string;
    jobId: string;
    rowId: string;
    payload: Record<string, unknown>;
  }) =>
    prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${input.tenantId}, true),
          set_config('app.current_user_id', ${input.userId}, true)
      `;
      const jobRows = await tx.$queryRaw<
        Array<{ job_id: string; job_status: string }>
      >`
        SELECT job_id, job_status
        FROM ingestion_jobs
        WHERE tenant_id = ${input.tenantId}::uuid
          AND job_id = ${input.jobId}::uuid
        FOR UPDATE
      `;
      if (jobRows.length !== 1) throw new IngestionJobNotFoundError();
      if (jobRows[0]!.job_status.toUpperCase() === "PROCESSING") {
        throw new IngestionJobNotRetryableError(
          "Rows cannot be edited while the worker is processing this job."
        );
      }

      let numericRowId: bigint;
      if (!/^[1-9]\d{0,18}$/.test(input.rowId)) {
        throw new IngestionJobNotFoundError();
      }
      try {
        numericRowId = BigInt(input.rowId);
      } catch {
        throw new IngestionJobNotFoundError();
      }
      if (numericRowId > 9_223_372_036_854_775_807n) {
        throw new IngestionJobNotFoundError();
      }
      const row = await tx.import_staging_rows.findFirst({
        where: {
          tenant_id: input.tenantId,
          job_id: input.jobId,
          staging_row_id: numericRowId
        },
        select: { validation_status: true }
      });
      if (!row) throw new IngestionJobNotFoundError();
      if (!["INVALID", "PARTIAL"].includes(row.validation_status)) {
        throw new IngestionJobNotRetryableError(
          "Only rejected or partial rows can be corrected."
        );
      }

      const saved = await tx.import_staging_rows.update({
        where: { staging_row_id: numericRowId },
        data: {
          raw_payload_json: toPrismaJson(input.payload),
          validation_status: "PENDING",
          validation_errors: null,
          committed_record_id: null,
          committed_table: null
        },
        select: { staging_row_id: true, validation_status: true }
      });
      await tx.ingestion_jobs.update({
        where: {
          tenant_id_job_id: {
            tenant_id: input.tenantId,
            job_id: input.jobId
          }
        },
        data: {
          job_status: "QUEUED",
          processing_attempts: 0,
          next_attempt_at: new Date(),
          error_log: null,
          ended_at: null,
          heartbeat_at: null
        }
      });
      return {
        id: saved.staging_row_id.toString(),
        status: saved.validation_status.toLowerCase()
      };
    }),

  retryIngestionJob: async (
    tenantId: string,
    userId: string,
    jobId: string
  ) => {
    return prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${tenantId}, true),
          set_config('app.current_user_id', ${userId}, true)
      `;
      const locked = await tx.$queryRaw<Array<{ job_id: string }>>`
        SELECT job_id
        FROM ingestion_jobs
        WHERE tenant_id = ${tenantId}::uuid
          AND job_id = ${jobId}::uuid
        FOR UPDATE
      `;
      if (locked.length !== 1) throw new IngestionJobNotFoundError();

      const job = await tx.ingestion_jobs.findFirst({
        where: { tenant_id: tenantId, job_id: jobId },
        select: { job_status: true }
      });
      if (!job) throw new IngestionJobNotFoundError();
      if (job.job_status.toUpperCase() !== "FAILED") {
        throw new IngestionJobNotRetryableError(
          "Only failed jobs can be retried."
        );
      }

      const pendingRows = await tx.import_staging_rows.count({
        where: {
          tenant_id: tenantId,
          job_id: jobId,
          validation_status: "PENDING"
        }
      });
      if (pendingRows === 0) {
        throw new IngestionJobNotRetryableError(
          "This job has no pending rows to retry. Review rejected or partial rows and upload a corrected file."
        );
      }

      const updated = await tx.ingestion_jobs.update({
        where: {
          tenant_id_job_id: { tenant_id: tenantId, job_id: jobId }
        },
        data: {
          job_status: "QUEUED",
          processing_attempts: 0,
          next_attempt_at: new Date(),
          error_log: null,
          started_at: null,
          ended_at: null,
          heartbeat_at: null
        },
        select: { job_id: true, job_status: true }
      });
      return { id: updated.job_id, status: updated.job_status.toLowerCase() };
    });
  },

  findBusinessFileImportByHash: async (
    tenantId: string,
    userId: string,
    contentSha256: string
  ) =>
    withTenantContext(tenantId, userId, async (tx) => {
      const source = await tx.data_sources.findFirst({
        where: {
          tenant_id: tenantId,
          source_type: "documents",
          collector_config: {
            path: ["content_sha256"],
            equals: contentSha256
          }
        },
        orderBy: { created_at: "desc" },
        select: {
          source_id: true,
          collector_config: true,
          ingestion_jobs: {
            orderBy: { created_at: "desc" },
            take: 1,
            select: {
              job_id: true,
              job_status: true,
              rows_processed: true,
              rows_failed: true,
              rows_partial: true,
              heartbeat_at: true,
              created_at: true
            }
          }
        }
      });
      const job = source?.ingestion_jobs[0];
      if (!source || !job) return null;
      const stagedRowCount = await tx.import_staging_rows.count({
        where: { tenant_id: tenantId, job_id: job.job_id }
      });
      return {
        sourceId: source.source_id,
        jobId: job.job_id,
        status: job.job_status.toLowerCase(),
        rowsProcessed: job.rows_processed ?? 0,
        rowsFailed: job.rows_failed ?? 0,
        rowsPartial: job.rows_partial ?? 0,
        stagedRowCount,
        extractionLeaseAt: job.heartbeat_at ?? job.created_at,
        config:
          source.collector_config &&
          typeof source.collector_config === "object" &&
          !Array.isArray(source.collector_config)
            ? (source.collector_config as Record<string, unknown>)
            : {}
      };
    }),

  reserveBusinessFileImport: async (input: {
    tenantId: string;
    userId: string;
    jobId: string;
    contentSha256: string;
    fileName: string;
    mimeType: string;
    fileSizeBytes: number;
    extractionUsageKb: number;
  }) =>
    prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${input.tenantId}, true),
          set_config('app.current_user_id', ${input.userId}, true)
      `;
      const lockKey =
        "manual-business-file:" + input.tenantId + ":" + input.contentSha256;
      // pg_advisory_xact_lock returns PostgreSQL `void`; use executeRaw so
      // Prisma does not try to decode a result column unsupported by the pg adapter.
      await tx.$executeRawUnsafe(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        lockKey
      );

      const existing = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_type: "documents",
          collector_config: {
            path: ["content_sha256"],
            equals: input.contentSha256
          }
        },
        orderBy: { created_at: "desc" },
        select: {
          source_id: true,
          collector_config: true,
          ingestion_jobs: {
            orderBy: { created_at: "desc" },
            take: 1,
            select: {
              job_id: true,
              job_status: true,
              rows_processed: true,
              rows_failed: true,
              rows_partial: true,
              heartbeat_at: true,
              created_at: true
            }
          }
        }
      });
      const existingJob = existing?.ingestion_jobs[0];
      const existingConfig =
        existing?.collector_config &&
        typeof existing.collector_config === "object" &&
        !Array.isArray(existing.collector_config)
          ? (existing.collector_config as Record<string, unknown>)
          : {};

      if (existing && existingJob) {
        const canReextract =
          (existingJob.job_status.toUpperCase() === "FAILED" &&
            existingConfig.last_failure_phase === "extraction") ||
          (existingJob.job_status.toUpperCase() === "EXTRACTING" &&
            Date.now() -
              (existingJob.heartbeat_at ?? existingJob.created_at ?? new Date(0)).getTime() >
              BUSINESS_FILE_EXTRACTION_LEASE_MS);
        if (canReextract) {
          const reservationAlreadyActive =
            existingConfig.extraction_usage_reservation_status === "reserved" &&
            existingConfig.extraction_usage_reserved_kb === input.extractionUsageKb;
          let usageRecordId =
            typeof existingConfig.extraction_usage_record_id === "string"
              ? existingConfig.extraction_usage_record_id
              : undefined;
          if (!reservationAlreadyActive) {
            const reservation = await reserveFeatureUsageInTransaction(
              tx,
              input.tenantId,
              "document_extraction",
              input.extractionUsageKb
            );
            usageRecordId = reservation.usageRecordId;
          }
          const nextConfig = {
            ...existingConfig,
            extraction_usage_reserved_kb: input.extractionUsageKb,
            ...(usageRecordId
              ? { extraction_usage_record_id: usageRecordId }
              : {}),
            extraction_usage_reservation_status: "reserved"
          };
          delete (nextConfig as Record<string, unknown>).last_failure_phase;
          await tx.data_sources.update({
            where: {
              tenant_id_source_id: {
                tenant_id: input.tenantId,
                source_id: existing.source_id
              }
            },
            data: { collector_config: toPrismaJson(nextConfig) }
          });
          await tx.ingestion_jobs.update({
            where: {
              tenant_id_job_id: {
                tenant_id: input.tenantId,
                job_id: existingJob.job_id
              }
            },
            data: {
              job_status: "EXTRACTING",
              processing_attempts: 0,
              error_log: null,
              started_at: null,
              ended_at: null,
              heartbeat_at: new Date()
            }
          });
          return {
            duplicate: false as const,
            sourceId: existing.source_id,
            jobId: existingJob.job_id
          };
        }
        const stagedRowCount = await tx.import_staging_rows.count({
          where: {
            tenant_id: input.tenantId,
            job_id: existingJob.job_id
          }
        });
        return {
          duplicate: true as const,
          sourceId: existing.source_id,
          jobId: existingJob.job_id,
          status: existingJob.job_status.toLowerCase(),
          rowsProcessed: existingJob.rows_processed ?? 0,
          rowsFailed: existingJob.rows_failed ?? 0,
          rowsPartial: existingJob.rows_partial ?? 0,
          stagedRowCount
        };
      }

      const usageReservation = await reserveFeatureUsageInTransaction(
        tx,
        input.tenantId,
        "document_extraction",
        input.extractionUsageKb
      );
      const source = await tx.data_sources.create({
        data: {
          tenant_id: input.tenantId,
          source_name: input.fileName.slice(0, 100),
          source_type: "documents",
          is_active: false,
          collector_config: {
            kind: "manual_business_file",
            original_file_name: input.fileName,
            content_type: input.mimeType,
            file_size_bytes: input.fileSizeBytes,
            content_sha256: input.contentSha256,
            extraction_usage_reserved_kb: input.extractionUsageKb,
            extraction_usage_record_id: usageReservation.usageRecordId,
            extraction_usage_reservation_status: "reserved"
          }
        },
        select: { source_id: true }
      });
      await tx.ingestion_jobs.create({
        data: {
          job_id: input.jobId,
          tenant_id: input.tenantId,
          source_id: source.source_id,
          job_status: "EXTRACTING",
          rows_processed: 0,
          rows_partial: 0,
          rows_failed: 0,
          rows_quarantined: 0,
          heartbeat_at: new Date()
        }
      });
      return {
        duplicate: false as const,
        sourceId: source.source_id,
        jobId: input.jobId
      };
    }),

  markBusinessFileExtractionFailed: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
    jobId: string;
  }) =>
    prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${input.tenantId}, true),
          set_config('app.current_user_id', ${input.userId}, true)
      `;
      const source = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_id: input.sourceId,
          source_type: "documents"
        },
        select: { collector_config: true }
      });
      if (!source) return;
      const failed = await tx.ingestion_jobs.updateMany({
        where: {
          tenant_id: input.tenantId,
          job_id: input.jobId,
          job_status: "EXTRACTING"
        },
        data: {
          job_status: "FAILED",
          error_log: "EXTRACTION_UPSTREAM_FAILURE",
          ended_at: new Date()
        }
      });
      if (failed.count !== 1) return;
      const config =
        source.collector_config &&
        typeof source.collector_config === "object" &&
        !Array.isArray(source.collector_config)
          ? (source.collector_config as Record<string, unknown>)
          : {};
      if (
        config.extraction_usage_reservation_status === "reserved" &&
        typeof config.extraction_usage_reserved_kb === "number"
      ) {
        await releaseFeatureUsageInTransaction(
          tx,
          input.tenantId,
          "document_extraction",
          config.extraction_usage_reserved_kb,
          typeof config.extraction_usage_record_id === "string"
            ? config.extraction_usage_record_id
            : undefined
        );
      }
      await tx.data_sources.update({
        where: {
          tenant_id_source_id: {
            tenant_id: input.tenantId,
            source_id: input.sourceId
          }
        },
        data: {
          collector_config: toPrismaJson({
            ...config,
            last_failure_phase: "extraction",
            extraction_usage_reservation_status: "released"
          })
        }
      });
    }),

  recordBusinessFileIngestion: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
    jobId: string;
    contentSha256: string;
    fileName: string;
    mimeType: string;
    fileSizeBytes: number;
    detectedType: string;
    headerCoverageRatio: number;
    rowsTruncatedToLimit: boolean | number;
    rowOutcomes: ExtractionRowOutcome[];
  }) => {
    // Keep both tenant and user session settings scoped to the write
    // transaction, exactly as required by the existing RLS insert policies.
    return prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${input.tenantId}, true),
          set_config('app.current_user_id', ${input.userId}, true)
      `;

      const source = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_id: input.sourceId,
          source_type: "documents",
          collector_config: {
            path: ["content_sha256"],
            equals: input.contentSha256
          }
        }
      });
      if (!source) throw new Error("Business file import reservation was lost.");

      const job = await tx.ingestion_jobs.findFirst({
        where: {
          tenant_id: input.tenantId,
          job_id: input.jobId,
          source_id: input.sourceId,
          job_status: "EXTRACTING"
        }
      });
      if (!job) throw new Error("Business file import is no longer extracting.");

      const sourceConfig =
        source.collector_config &&
        typeof source.collector_config === "object" &&
        !Array.isArray(source.collector_config)
          ? (source.collector_config as Record<string, unknown>)
          : {};
      await tx.data_sources.update({
        where: {
          tenant_id_source_id: {
            tenant_id: input.tenantId,
            source_id: input.sourceId
          }
        },
        data: {
          collector_config: toPrismaJson({
            ...sourceConfig,
            kind: "manual_business_file",
            original_file_name: input.fileName,
            content_type: input.mimeType,
            file_size_bytes: input.fileSizeBytes,
            content_sha256: input.contentSha256,
            detected_type: input.detectedType,
            header_coverage_ratio: input.headerCoverageRatio,
            rows_truncated_to_limit: input.rowsTruncatedToLimit,
            extraction_usage_reservation_status: "committed"
          })
        }
      });
      await tx.ingestion_jobs.update({
        where: {
          tenant_id_job_id: {
            tenant_id: input.tenantId,
            job_id: input.jobId
          }
        },
        data: {
          job_status: "QUEUED",
          error_log: null,
          next_attempt_at: new Date(),
          heartbeat_at: null
        }
      });

      const stagedRows = input.rowOutcomes.map((outcome) => {
        const mapped = mapExtractionOutcomeToStagingRow(
          input.tenantId,
          input.jobId,
          outcome
        );

        return {
          tenant_id: mapped.tenant_id,
          job_id: mapped.job_id,
          raw_payload_json: toPrismaJson(mapped.raw_payload),
          validation_status: mapped.validation_status,
          validation_errors: mapped.validation_errors
        };
      });

      await writeStagingRowsInBatches(stagedRows, async (batch) => {
        await tx.import_staging_rows.createMany({
          data: batch
        });
      });

      return { source, job, stagedRowCount: stagedRows.length };
    }, { timeout: BUSINESS_FILE_STAGING_TRANSACTION_TIMEOUT_MS });
  },

  createPersistentSource: async (input: {
    tenantId: string;
    userId: string;
    name: string;
    sourceType:
      | "shopify"
      | "postgresql"
      | "mysql"
      | "sqlserver"
      | "ga4"
      | "website";
    syncFrequencyMinutes: number;
    sourceUrl?: string;
    metadata: JsonObject;
  }) => {
    return withTenantContext(input.tenantId, input.userId, async (tx) => {
      const lockKey = "connected-data-sources:" + input.tenantId;
      // The lock function returns `void`, which the pg adapter cannot decode
      // through queryRaw. Execute it without requesting result columns.
      await tx.$executeRawUnsafe(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        lockKey
      );

      const duplicate = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_type: input.sourceType,
          is_active: true,
          ...(input.sourceUrl
            ? { source_url: input.sourceUrl }
            : {
                source_name: {
                  equals: input.name,
                  mode: "insensitive"
                }
              })
        },
        select: { source_id: true }
      });
      if (duplicate) throw new DuplicateDataSourceError();

      const capacity = await getConnectedDataSourceCapacityInTransaction(
        tx,
        input.tenantId
      );
      if (
        !capacity.included ||
        (!capacity.isUnlimited &&
          capacity.limit !== null &&
          capacity.currentUsage >= capacity.limit)
      ) {
        throw new ConnectedSourceCapacityError({
          message: capacity.included
            ? "The connected data source limit has been reached."
            : "Connected data sources are not available for this subscription.",
          featureIncluded: capacity.included,
          currentUsage: capacity.currentUsage,
          limit: capacity.limit,
          remaining: capacity.remaining,
          isUnlimited: capacity.isUnlimited
        });
      }

      return tx.data_sources.create({
        data: {
          tenant_id: input.tenantId,
          source_name: input.name,
          source_type: input.sourceType,
          source_url: input.sourceUrl ?? null,
          // Never store plaintext connector credentials here.
          connection_credentials_vault: null,
          sync_frequency_minutes: input.syncFrequencyMinutes,
          // Active means configured, not that connection testing succeeded.
          is_active: true,
          collector_config: input.metadata
        },
        select: {
          source_id: true,
          source_name: true,
          source_type: true,
          source_url: true,
          sync_frequency_minutes: true,
          is_active: true,
          collector_config: true,
          last_synced_at: true,
          created_at: true
        }
      });
    });
  },

  setPersistentSourceActive: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
    isActive: boolean;
  }) => {
    return withTenantContext(input.tenantId, input.userId, async (tx) => {
      const lockKey = "connected-data-sources:" + input.tenantId;
      // The lock function returns `void`, which the pg adapter cannot decode
      // through queryRaw. Execute it without requesting result columns.
      await tx.$executeRawUnsafe(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        lockKey
      );

      const source = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_id: input.sourceId,
          source_type: { in: [...PERSISTENT_SOURCE_TYPES] }
        }
      });
      if (!source) throw new DataSourceNotFoundError();

      if (input.isActive && hasDisconnectedConnection(source.collector_config)) {
        throw new DataSourceReconnectRequiredError();
      }

      if (input.isActive && !source.is_active) {
        const duplicate = await tx.data_sources.findFirst({
          where: {
            tenant_id: input.tenantId,
            is_active: true,
            source_type: source.source_type,
            source_id: { not: source.source_id },
            ...(source.source_url
              ? { source_url: source.source_url }
              : {
                  source_name: {
                    equals: source.source_name,
                    mode: "insensitive"
                  }
                })
          },
          select: { source_id: true }
        });
        if (duplicate) throw new DuplicateDataSourceError();
      }

      if (input.isActive && !source.is_active) {
        const capacity = await getConnectedDataSourceCapacityInTransaction(
          tx,
          input.tenantId
        );
        if (
          !capacity.included ||
          (!capacity.isUnlimited &&
            capacity.limit !== null &&
            capacity.currentUsage >= capacity.limit)
        ) {
          throw new ConnectedSourceCapacityError({
            message: capacity.included
              ? "The connected data source limit has been reached."
              : "Connected data sources are not available for this subscription.",
            featureIncluded: capacity.included,
            currentUsage: capacity.currentUsage,
            limit: capacity.limit,
            remaining: capacity.remaining,
            isUnlimited: capacity.isUnlimited
          });
        }
      }

      return tx.data_sources.update({
        where: {
          tenant_id_source_id: {
            tenant_id: input.tenantId,
            source_id: input.sourceId
          }
        },
        data: { is_active: input.isActive },
        select: {
          source_id: true,
          source_name: true,
          source_type: true,
          source_url: true,
          sync_frequency_minutes: true,
          is_active: true,
          collector_config: true,
          last_synced_at: true,
          created_at: true
        }
      });
    });
  },

  disconnectPersistentSource: async (input: {
    tenantId: string;
    userId: string;
    sourceId: string;
  }) => {
    return withTenantContext(input.tenantId, input.userId, async (tx) => {
      const lockKey = "connected-data-sources:" + input.tenantId;
      await tx.$executeRawUnsafe(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        lockKey
      );

      const source = await tx.data_sources.findFirst({
        where: {
          tenant_id: input.tenantId,
          source_id: input.sourceId,
          source_type: { in: [...PERSISTENT_SOURCE_TYPES] }
        },
        select: {
          source_id: true,
          collector_config: true
        }
      });
      if (!source) throw new DataSourceNotFoundError();

      const config =
        source.collector_config &&
        typeof source.collector_config === "object" &&
        !Array.isArray(source.collector_config)
          ? (source.collector_config as Record<string, unknown>)
          : {};

      return tx.data_sources.update({
        where: {
          tenant_id_source_id: {
            tenant_id: input.tenantId,
            source_id: source.source_id
          }
        },
        data: {
          is_active: false,
          connection_credentials_vault: null,
          collector_config: toPrismaJson({
            ...config,
            ceopro_connection_status: "disconnected",
            ceopro_disconnected_at: new Date().toISOString()
          })
        },
        select: {
          source_id: true,
          source_name: true,
          source_type: true,
          source_url: true,
          sync_frequency_minutes: true,
          is_active: true,
          collector_config: true,
          last_synced_at: true,
          created_at: true
        }
      });
    });
  },

  countActivePersistentSources: async (tenantId: string, userId: string) => {
    return withTenantContext(tenantId, userId, (tx) =>
      tx.data_sources.count({
        where: {
          tenant_id: tenantId,
          is_active: true,
          // Manual document uploads do not consume persistent-source capacity.
          source_type: {
            in: [
              "shopify",
              "postgresql",
              "mysql",
              "sqlserver",
              "ga4",
              "website",
              "OWN_SYSTEM_CONNECTOR"
            ]
          }
        }
      })
    );
  },

  findPersistentSourceById: async (
    tenantId: string,
    userId: string,
    sourceId: string
  ) => {
    return withTenantContext(tenantId, userId, (tx) =>
      tx.data_sources.findFirst({
        where: {
          tenant_id: tenantId,
          source_id: sourceId,
          source_type: {
            in: [
              "shopify",
              "postgresql",
              "mysql",
              "sqlserver",
              "ga4",
              "website",
              "OWN_SYSTEM_CONNECTOR"
            ]
          }
        },
        select: {
          source_id: true,
          source_name: true,
          source_type: true,
          source_url: true,
          sync_frequency_minutes: true,
          is_active: true,
          collector_config: true,
          last_synced_at: true,
          created_at: true
        }
      })
    );
  }
};

function toPrismaJson(value: unknown): Prisma.InputJsonValue {
  const serialized = JSON.stringify(value);
  return serialized === undefined
    ? {}
    : (JSON.parse(serialized) as Prisma.InputJsonValue);
}
