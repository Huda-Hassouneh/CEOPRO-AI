import { MIMEType } from "util";
import { prisma } from "../../../config/database.js";
import { ACCESS_GRANTING_STATUSES } from "../../../constants/subscription.js";
import { getCurrentCapacityUsage } from "../service/capacity.service.js";
import { hasRemainingCapacity } from "../service/entitlement-policy.js";

const accessStatuses = [...ACCESS_GRANTING_STATUSES];
export type RemainingUsageInfo = {
  subscriptionId: string;
  featureId: string;
  featureCode: string;
  type: string;
  aggregationType: string;
  unit: string | null;
  resetCycle: string;
  periodStart: Date;
  periodEnd: Date;
  limit: number | null;
  currentUsage: number;
  remaining: number | null;
  isUnlimited: boolean;
  isExceeded: boolean;
};
export async function ensureUsageAllocationsForSubscription(input: {
  subscriptionId: string;
  planId: string;
  periodStart: Date;
  periodEnd: Date;
}) {
  const planFeatures = await prisma.planFeature.findMany({
    where: { plan_id: input.planId },
    include: { feature: true }
  });

  const meteredFeatures = planFeatures.filter(
    (planFeature) =>
      planFeature.feature.type === "limit" &&
      planFeature.feature.aggregationType === "sum"
  );

  await prisma.$transaction(async (tx) => {
    for (const planFeature of meteredFeatures) {
      const feature = planFeature.feature;

      if (feature.resetCycle === "lifetime") {
        const existing = await tx.subscriptionUsage.findFirst({
          where: {
            subscription_id: input.subscriptionId,
            feature_id: planFeature.feature_id
          }
        });
        if (existing) continue;
      }

      await tx.subscriptionUsage.upsert({
        where: {
          subscription_id_feature_id_period_start: {
            subscription_id: input.subscriptionId,
            feature_id: planFeature.feature_id,
            period_start: input.periodStart
          }
        },
        update: { period_end: input.periodEnd },
        create: {
          subscription_id: input.subscriptionId,
          feature_id: planFeature.feature_id,
          current_usage: 0,
          period_start: input.periodStart,
          period_end: input.periodEnd
        }
      });
    }
  });
}

export const usageRepository = {
  getCurrentUsageByTenant: async (tenantId: string) => {
    const now = new Date();
    return prisma.subscription.findFirst({
      where: { tenantId, status: { in: accessStatuses } },
      include: {
        plan: { include: { planFeatures: { include: { feature: true } } } },
        subscriptionUsages: {
          where: {
            OR: [
              { feature: { resetCycle: "lifetime" } },
              { period_start: { lte: now }, period_end: { gt: now } }
            ]
          },
          include: { feature: true }
        }
      }
    });
  },

  increment: async (usageId: string, amount = 1) =>
    prisma.subscriptionUsage.update({
      where: { id: usageId },
      data: { current_usage: { increment: amount } }
    })
};

export async function getFeatureAccessInfo(
  tenantId: string,
  featureCode: string
) {
  const subscription = await prisma.subscription.findFirst({
    where: {
      tenantId,
      status: { in: accessStatuses }
    },
    include: {
      plan: {
        include: {
          planFeatures: {
            where: { feature: { code: featureCode } },
            include: { feature: true }
          }
        }
      }
    }
  });

  return {
    subscription,
    planFeature: subscription?.plan.planFeatures[0] ?? null
  };
}

export const incrementUsage = async (
  tenantId: string,
  featureCode: string,
  amount = 1
) => {
  if (!Number.isInteger(amount) || amount <= 0) {
    throw new Error("Usage amount must be a positive integer.");
  }

  const { subscription, planFeature } = await getFeatureAccessInfo(
    tenantId,
    featureCode
  );

  if (!subscription || !planFeature) return null;

  if (
    planFeature.feature.type !== "limit" ||
    planFeature.feature.aggregationType !== "sum"
  ) {
    throw new Error(
      `Feature '${featureCode}' does not use cumulative SUM usage and cannot be incremented.`
    );
  }

  await ensureUsageAllocationsForSubscription({
    subscriptionId: subscription.id,
    planId: subscription.planId,
    periodStart: subscription.currentPeriodStart,
    periodEnd: subscription.currentPeriodEnd
  });

  const now = new Date();
  const usageRecord = await prisma.subscriptionUsage.findFirst({
    where: {
      subscription_id: subscription.id,
      feature_id: planFeature.feature_id,
      OR: [
        { feature: { resetCycle: "lifetime" } },
        { period_start: { lte: now }, period_end: { gt: now } }
      ]
    }
  });

  if (!usageRecord) return null;

  return usageRepository.increment(usageRecord.id, amount);
};

export const getRemainingUsage = async (
  tenantId: string,
  featureCode: string
): Promise<RemainingUsageInfo | null> => {
  const { subscription, planFeature } = await getFeatureAccessInfo(
    tenantId,
    featureCode
  );

  if (!subscription || !planFeature) return null;

  const feature = planFeature.feature;
  let currentUsage = 0;

  if (feature.type === "limit" && feature.aggregationType === "max") {
    currentUsage = await getCurrentCapacityUsage(tenantId, featureCode);
  } else if (feature.type === "limit" && feature.aggregationType === "sum") {
    await ensureUsageAllocationsForSubscription({
      subscriptionId: subscription.id,
      planId: subscription.planId,
      periodStart: subscription.currentPeriodStart,
      periodEnd: subscription.currentPeriodEnd
    });

    const now = new Date();
    const usageRecord = await prisma.subscriptionUsage.findFirst({
      where: {
        subscription_id: subscription.id,
        feature_id: feature.id,
        OR: [
          { feature: { resetCycle: "lifetime" } },
          { period_start: { lte: now }, period_end: { gt: now } }
        ]
      }
    });
    currentUsage = usageRecord?.current_usage ?? 0;
  }

  if (feature.type !== "limit") {
    return {
      subscriptionId: subscription.id,
      featureId: feature.id,
      featureCode: feature.code,
      type: feature.type,
      aggregationType: feature.aggregationType,
      unit: feature.unit ?? null,
      resetCycle: feature.resetCycle,
      periodStart: subscription.currentPeriodStart,
      periodEnd: subscription.currentPeriodEnd,
      limit: null,
      currentUsage: 0,
      remaining: null,
      isUnlimited: true,
      isExceeded: false
    };
  }

  if (planFeature.limit_value === null) {
    return {
      subscriptionId: subscription.id,
      featureId: feature.id,
      featureCode: feature.code,
      type: feature.type,
      aggregationType: feature.aggregationType,
      unit: feature.unit ?? null,
      resetCycle: feature.resetCycle,
      periodStart: subscription.currentPeriodStart,
      periodEnd: subscription.currentPeriodEnd,
      limit: null,
      currentUsage,
      remaining: null,
      isUnlimited: true,
      isExceeded: false
    };
  }

  const limit = planFeature.limit_value;
  const remaining = Math.max(0, limit - currentUsage);

  return {
    subscriptionId: subscription.id,
    featureId: feature.id,
    featureCode: feature.code,
    type: feature.type,
    aggregationType: feature.aggregationType,
    unit: feature.unit ?? null,
    resetCycle: feature.resetCycle,
    periodStart: subscription.currentPeriodStart,
    periodEnd: subscription.currentPeriodEnd,
    limit,
    currentUsage,
    remaining,
    isUnlimited: false,
    isExceeded: currentUsage >= limit
  };
};

export async function assertFeatureCapacity(input: {
  tenantId: string;
  featureCode: string;
  additionalAmount?: number;
}) {
  const additionalAmount = input.additionalAmount ?? 1;
  if (!Number.isFinite(additionalAmount) || additionalAmount <= 0) {
    throw new Error("additionalAmount must be a positive number.");
  }

  const entitlement = await getRemainingUsage(
    input.tenantId,
    input.featureCode
  );
  if (!entitlement)
    return { allowed: false as const, reason: "FEATURE_NOT_INCLUDED" as const };
  if (entitlement.aggregationType !== "max") {
    throw new Error(
      `Feature '${input.featureCode}' is not a MAX capacity feature.`
    );
  }
  if (entitlement.isUnlimited) return { allowed: true as const, entitlement };

  const allowed = hasRemainingCapacity({
    currentUsage: entitlement.currentUsage,
    limit: entitlement.limit,
    additionalAmount
  });
  return {
    allowed,
    entitlement,
    reason: allowed ? undefined : ("CAPACITY_REACHED" as const)
  };
}

export const documentsRepo = {
  getDocuments: async ({
    tenant_id,
    page,
    pageSize
  }: {
    tenant_id: string;
    page: number;
    pageSize: number;
  }) => {
    const documents = await prisma.rag_documents_metadata.findMany({
      where: { tenant_id },
      orderBy: { uploaded_at: "desc" },
      skip: (page - 1) * pageSize,
      take: pageSize
    });
    return documents;
  },
  getCountDocuments: async (tenant_id: string) => {
    return await prisma.rag_documents_metadata.count({
      where: { tenant_id }
    });
  },
  getChunkById: async (tenantId: string, chunkId: string) => {
    return await prisma.rag_document_chunks.findFirst({
      where: {
        tenant_id: tenantId, // Security boundary
        chunk_id: chunkId
      },
      include: {
        rag_documents_metadata: {
          select: {
            file_name: true
          }
        }
      }
    });
  },
  insertRagDocumentMeta: async ({
    tenantId,
    filename,
    minio_object_key,
    fileSize,
    mimetype,
    userId
  }: {
    tenantId: string;
    filename: string;
    minio_object_key: string;
    fileSize: bigint;
    mimetype: string;
    userId: string;
  }) => {
    await prisma.rag_documents_metadata.create({
      data: {
        tenant_id: tenantId,
        file_name: filename,
        storage_bucket_path: minio_object_key,
        file_size_bytes: BigInt(fileSize), // Schema expects BigInt[cite: 6]
        content_type: mimetype,
        uploaded_by_user_id: userId
      }
    });
  }
};
