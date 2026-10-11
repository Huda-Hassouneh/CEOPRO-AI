import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type {
  ExtractionRowOutcome,
  JsonObject
} from "../types/dataconnection.types.js";
import { mapExtractionOutcomeToStagingRow } from "../service/extraction-staging.mapper.js";

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

const mapJobStatusToConnectionStatus = (dbStatus?: string) => {
  if (!dbStatus) return "notSynced";

  switch (dbStatus.toUpperCase()) {
    case "QUEUED":
    case "PROCESSING":
      return "processing";
    case "COMPLETED":
      return "connected";
    case "FAILED":
      return "needsAttention";
    default:
      return "unknown";
  }
};

const mapJobStatusToImportStatus = (dbStatus: string) => {
  const statusMap: Record<string, string> = {
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
          is_active: true
        },
        include: {
          ingestion_jobs: {
            orderBy: { created_at: "desc" }
          }
        }
      });

      const connectedSources = dataSources.map((source) => {
        const latestJob = source.ingestion_jobs[0];
        const totalRecords = source.ingestion_jobs.reduce(
          (sum, job) => sum + (job.rows_processed || 0),
          0
        );
        const status = mapJobStatusToConnectionStatus(latestJob?.job_status);
        const actions = ["details"];

        if (source.source_type === "documents") {
          actions.push("uploadVersion");
        }
        if (status === "needsAttention") {
          actions.push("reconnect");
        }

        return {
          id: source.source_id,
          type: source.source_type,
          name: localized(source.source_name, source.source_name),
          status,
          lastUpdatedAt: latestJob?.ended_at
            ? latestJob.ended_at.toISOString()
            : (source.created_at?.toISOString() ?? null),
          recordCount: totalRecords > 0 ? totalRecords : null,
          categories: getCategoriesByType(source.source_type),
          // Preserved for compatibility with the existing frontend contract.
          // This does not independently verify an external connection.
          dataStatus: "verified",
          actions
        };
      });

      // Deliberately NOT limited to active sources: manual uploads belong
      // in recentImports even though they are not persistent connections.
      const recentImports = await getRecentActivityInTransaction(
        tx,
        tenantId,
        5
      );

      return {
        connectedSources,
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

  recordBusinessFileIngestion: async (input: {
    tenantId: string;
    userId: string;
    jobId: string;
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

      // Manual uploads are not persistent connected integrations.
      // They remain absent from connectedSources but appear in recentImports.
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
            detected_type: input.detectedType,
            header_coverage_ratio: input.headerCoverageRatio,
            rows_truncated_to_limit: input.rowsTruncatedToLimit
          }
        }
      });

      const job = await tx.ingestion_jobs.create({
        data: {
          job_id: input.jobId,
          tenant_id: input.tenantId,
          source_id: source.source_id,
          job_status: "QUEUED",
          rows_processed: 0,
          rows_partial: 0,
          rows_failed: 0,
          rows_quarantined: 0
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

      if (stagedRows.length > 0) {
        await tx.import_staging_rows.createMany({ data: stagedRows });
      }

      return { source, job, stagedRowCount: stagedRows.length };
    });
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
    metadata: JsonObject;
  }) => {
    return withTenantContext(input.tenantId, input.userId, (tx) =>
      tx.data_sources.create({
        data: {
          tenant_id: input.tenantId,
          source_name: input.name,
          source_type: input.sourceType,
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
          sync_frequency_minutes: true,
          is_active: true,
          collector_config: true,
          last_synced_at: true,
          created_at: true
        }
      })
    );
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
              "website"
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
              "website"
            ]
          }
        },
        select: {
          source_id: true,
          source_name: true,
          source_type: true,
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
