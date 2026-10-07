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
  if (!dbStatus) {
    return "notSynced";
  }

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
  const status = dbStatus.toUpperCase();

  const statusMap: Record<string, string> = {
    QUEUED: "Processing",
    PROCESSING: "Processing",
    COMPLETED: "Completed",
    FAILED: "Failed"
  };

  return statusMap[status] || dbStatus;
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

// --- 2. Repository Methods ---

export const dataManagementRepo = {
  /**
   * Returns recent Data Connection ingestion activity.
   *
   * Important:
   * This intentionally reads only from ingestion_jobs.
   *
   * RAG documents belong to the Knowledge Assistant domain and must not be
   * mixed into the Data Connection activity feed.
   */

  getRecentActivity: async (tenantId: string, limit = 10) => {
    const jobs = await prisma.ingestion_jobs.findMany({
      where: {
        tenant_id: tenantId
      },
      include: {
        data_sources: {
          select: {
            source_name: true,
            source_type: true
          }
        }
      },
      orderBy: {
        created_at: "desc"
      },
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

        /*
         * With the current schema, ingestion_jobs does not contain
         * original_file_name.
         *
         * For document/file sources, source_name is therefore the best
         * available persisted identifier.
         *
         * If you later add a dedicated input_file_name column to
         * ingestion_jobs, replace this with that field.
         */
        name: isBusinessFile ? sourceName : `Sync - ${sourceName}`,

        type: getActivityType(sourceType),

        // Real status from ingestion_jobs.
        status: mapJobStatusToImportStatus(job.job_status)
      };
    });
  },

  /**
   * Returns the Data Connection overview.
   */
  getDataConnectionsOverview: async (tenantId: string) => {
    const dataSources = await prisma.data_sources.findMany({
      where: {
        tenant_id: tenantId,
        is_active: true
      },
      include: {
        ingestion_jobs: {
          orderBy: {
            created_at: "desc"
          }
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

        /*
         * Preserved to avoid breaking the existing frontend contract.
         * This should be audited separately if "verified" has a strict
         * business meaning in your UI.
         */
        dataStatus: "verified",

        actions
      };
    });

    const recentImports = await dataManagementRepo.getRecentActivity(
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
    return prisma.$transaction(async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${input.tenantId}, true),
          set_config('app.current_user_id', ${input.userId}, true)
      `;

      /*
       * A manual uploaded sales file is an ingestion source,
       * but it is NOT a persistent connected integration.
       *
       * Therefore is_active=false keeps it out of
       * connectedSources while its ingestion job still appears
       * in recentImports.
       */
      const source = await tx.data_sources.create({
        data: {
          tenant_id: input.tenantId,

          // schema currently limits source_name to 100 chars
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

      return {
        source,
        job,
        stagedRowCount: stagedRows.length
      };
    });
  },
  createPersistentSource: async (input: {
    tenantId: string;
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
    return prisma.data_sources.create({
      data: {
        tenant_id: input.tenantId,
        source_name: input.name,
        source_type: input.sourceType,

        /*
         * Do not persist raw credentials here.
         *
         * Connector-specific OAuth / vault logic can
         * populate this later with a secret reference.
         */
        connection_credentials_vault: null,

        sync_frequency_minutes: input.syncFrequencyMinutes,

        /*
         * A newly configured persistent source consumes
         * connected_data_sources capacity.
         *
         * This does NOT mean the external connection
         * has already been successfully tested.
         */
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
    });
  },

  countActivePersistentSources: async (tenantId: string) => {
    return prisma.data_sources.count({
      where: {
        tenant_id: tenantId,
        is_active: true,

        /*
         * Manual uploaded files are recorded with
         * source_type = documents and is_active = false.
         *
         * This explicit filter also prevents them from
         * ever consuming persistent-source capacity.
         */
        source_type: {
          in: ["shopify", "postgresql", "mysql", "sqlserver", "ga4", "website"]
        }
      }
    });
  },

  findPersistentSourceById: async (tenantId: string, sourceId: string) => {
    return prisma.data_sources.findFirst({
      where: {
        tenant_id: tenantId,
        source_id: sourceId,
        source_type: {
          in: ["shopify", "postgresql", "mysql", "sqlserver", "ga4", "website"]
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
    });
  }
};

function toPrismaJson(value: unknown): Prisma.InputJsonValue {
  const serialized = JSON.stringify(value);
  return serialized === undefined
    ? {}
    : (JSON.parse(serialized) as Prisma.InputJsonValue);
}
