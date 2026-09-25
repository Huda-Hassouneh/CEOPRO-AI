import { prisma } from "../../../config/database.js";

export const MAX_CAPACITY_FEATURE_CODES = Object.freeze([
  "tracked_competitors",
  "tracked_products",
  "connected_data_sources",
  "team_members",
  "document_storage_gb"
] as const);

export type MaxCapacityFeatureCode =
  (typeof MAX_CAPACITY_FEATURE_CODES)[number];

export function isMaxCapacityFeatureCode(
  featureCode: string
): featureCode is MaxCapacityFeatureCode {
  return (MAX_CAPACITY_FEATURE_CODES as readonly string[]).includes(featureCode);
}

export async function getCurrentCapacityUsage(
  tenantId: string,
  featureCode: string
): Promise<number> {
  switch (featureCode) {
    case "tracked_competitors":
      return prisma.tenant_competitors.count({
        where: { tenant_id: tenantId, is_tracked: true }
      });

    case "tracked_products":
      return prisma.products.count({
        where: { tenant_id: tenantId, deleted_at: null }
      });

    case "connected_data_sources":
      return prisma.data_sources.count({
        where: { tenant_id: tenantId, is_active: true }
      });

    case "team_members":
      return prisma.tenantUser.count({
        where: { tenantId, removedAt: null }
      });

    case "document_storage_gb": {
      const aggregate = await prisma.rag_documents_metadata.aggregate({
        where: { tenant_id: tenantId },
        _sum: { file_size_bytes: true }
      });
      const bytes = aggregate._sum.file_size_bytes ?? 0n;
      if (bytes <= 0n) return 0;
      const gibibytes = Number(bytes) / (1024 ** 3);
      return Math.round(gibibytes * 1000) / 1000;
    }

    default:
      throw new Error(
        `No authoritative capacity resolver exists for feature '${featureCode}'.`
      );
  }
}
