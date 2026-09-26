import { prisma } from "../../../config/database.js"; // Adjust path to your Prisma client

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

const mapJobStatusToConnectionStatus = (dbStatus: string | undefined) => {
  if (!dbStatus) return "connected";
  const status = dbStatus.toUpperCase();
  if (status === "QUEUED" || status === "PROCESSING") return "processing";
  if (status === "FAILED") return "needsAttention";
  return "connected";
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

const getFileTypeIndicator = (mimeType: string | null) => {
  if (!mimeType) return "File";
  if (mimeType.includes("csv")) return "CSV";
  if (mimeType.includes("pdf")) return "PDF";
  if (mimeType.includes("spreadsheetml")) return "Excel";
  return "Document";
};

// --- 2. Integrated Repository Methods ---

export const dataManagementRepo = {
  /**
   * Fetches and merges automated jobs and manual file uploads into a unified timeline.
   */
  getRecentActivity: async (tenantId: string, limit = 10) => {
    // Fetch Automated Connections & Syncs
    const jobs = await prisma.ingestion_jobs.findMany({
      where: { tenant_id: tenantId },
      include: {
        data_sources: {
          select: { source_name: true, source_type: true }
        }
      },
      orderBy: { created_at: "desc" },
      take: limit
    });

    // Fetch Manual File Uploads
    const files = await prisma.rag_documents_metadata.findMany({
      where: { tenant_id: tenantId },
      orderBy: { uploaded_at: "desc" },
      take: limit
    });

    // Normalize automated jobs
    const mappedJobs = jobs.map((job) => {
      const sourceName = job.data_sources?.source_name || "Unknown Source";
      return {
        id: job.job_id,
        date: job.started_at || job.created_at,
        source: localized(sourceName, sourceName),
        name: `Sync - ${sourceName}`,
        type: "Connection",
        status: mapJobStatusToImportStatus(job.job_status)
      };
    });

    // Normalize manual file uploads
    const mappedFiles = files.map((file) => ({
      id: file.document_id,
      date: file.uploaded_at,
      source: localized("Business Data Files", "ملفات بيانات الأعمال"),
      name: file.file_name, // Real file name from the database
      type: getFileTypeIndicator(file.content_type),
      status: "Completed" // Uploads stored in DB are inherently completed
    }));

    // Merge, sort by date descending, and slice to the requested limit
    const combinedActivity = [...mappedJobs, ...mappedFiles].sort((a, b) => {
      const dateA = a.date ? new Date(a.date).getTime() : 0;
      const dateB = b.date ? new Date(b.date).getTime() : 0;
      return dateB - dateA;
    });

    return combinedActivity.slice(0, limit);
  },

  /**
   * Provides the overview dashboard data, utilizing getRecentActivity for exact accuracy.
   */
  getDataConnectionsOverview: async (tenantId: string) => {
    // 1. Fetch Active Data Sources and their nested jobs
    const dataSources = await prisma.data_sources.findMany({
      where: { tenant_id: tenantId, is_active: true },
      include: {
        ingestion_jobs: {
          orderBy: { created_at: "desc" }
        }
      }
    });

    // 2. Map Connected Sources
    const connectedSources = dataSources.map((source) => {
      const latestJob = source.ingestion_jobs[0];
      const totalRecords = source.ingestion_jobs.reduce(
        (sum, job) => sum + (job.rows_processed || 0),
        0
      );

      const status = mapJobStatusToConnectionStatus(latestJob?.job_status);
      const actions = ["details"];

      if (source.source_type === "documents") actions.push("uploadVersion");
      if (status === "needsAttention") actions.push("reconnect");

      return {
        id: source.source_id,
        type: source.source_type,
        name: localized(source.source_name, source.source_name),
        status,
        lastUpdatedAt: latestJob?.ended_at
          ? latestJob.ended_at.toISOString()
          : source.created_at?.toISOString() || new Date().toISOString(),
        recordCount: totalRecords > 0 ? totalRecords : null,
        categories: getCategoriesByType(source.source_type),
        dataStatus: "verified",
        actions
      };
    });

    // 3. Fetch Recent Imports using the unified query method
    // This dynamically handles BOTH files and jobs seamlessly.
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
  }
};
