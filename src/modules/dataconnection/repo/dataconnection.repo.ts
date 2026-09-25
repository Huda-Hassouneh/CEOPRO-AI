import { prisma } from "../../../config/database.js";

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
  if (status === "QUEUED" || status === "PROCESSING") return "processing";
  if (status === "FAILED") return "failed";
  return "completed";
};

export const getDataConnectionsOverview = async (tenant_id: string) => {
  // 1. Fetch Data Sources and their nested Ingestion Jobs[cite: 8]
  const dataSources = await prisma.data_sources.findMany({
    where: { tenant_id, is_active: true },
    include: {
      ingestion_jobs: {
        orderBy: { created_at: "desc" }
      }
    }
  });

  // 2. Fetch Recent Ingestion Jobs directly for the Recent Imports table[cite: 8]
  const recentJobs = await prisma.ingestion_jobs.findMany({
    where: { tenant_id },
    orderBy: { created_at: "desc" },
    take: 5,
    include: {
      data_sources: {
        select: { source_name: true, source_type: true }
      }
    }
  });

  // 3. Map Connected Sources
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

  // 4. Map Recent Imports
  const recentImports = recentJobs.map((job) => {
    const sourceType = job.data_sources?.source_type || "unknown";
    const sourceName = job.data_sources?.source_name || "Unknown Source";

    // Simulate filename or import name since it is not explicitly stored in ingestion_jobs[cite: 8]
    const importName =
      sourceType === "website"
        ? localized("Scheduled website scan", "فحص الموقع المجدول")
        : sourceType === "documents"
          ? `data-update-${job.created_at?.toISOString().split("T")[0]}.csv`
          : `Sync - ${sourceName}`;

    return {
      id: job.job_id,
      date: job.created_at?.toISOString() || new Date().toISOString(),
      source: localized(sourceName, sourceName),
      name: importName,
      type: sourceType === "documents" ? "csv" : "connection",
      status: mapJobStatusToImportStatus(job.job_status)
    };
  });

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
};
