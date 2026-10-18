import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import { COUNTED_CONNECTED_SOURCE_TYPES } from "../../../constants/data-source-types.js";

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

    const subscription = await prisma.subscription.findFirst({

      where: { tenantId, status: { in: accessStatuses } },

      include: {

        plan: { include: { planFeatures: { include: { feature: true } } } }

      }

    });

    if (!subscription) return null;

    await ensureUsageAllocationsForSubscription({

      subscriptionId: subscription.id,

      planId: subscription.planId,

      periodStart: subscription.currentPeriodStart,

      periodEnd: subscription.currentPeriodEnd

    });

    const subscriptionUsages = await prisma.subscriptionUsage.findMany({

      where: {

        subscription_id: subscription.id,

        OR: [

          { feature: { resetCycle: "lifetime" } },

          { period_start: subscription.currentPeriodStart }

        ]

      },

      include: { feature: true }

    });

    return {

      ...subscription,

      subscriptionUsages

    };

  },

  increment: async (usageId: string, amount = 1) =>

    prisma.subscriptionUsage.update({

      where: { id: usageId },

      data: { current_usage: { increment: amount } }

    })

};

type FeatureAccessClient = Pick<typeof prisma, "subscription">;

export async function getFeatureAccessInfo(
  tenantId: string,
  featureCode: string,
  client: FeatureAccessClient = prisma
) {

  const subscription = await client.subscription.findFirst({

    where: {

      tenantId,

      status: { in: accessStatuses }

    },

    orderBy: [{ updatedAt: "desc" }, { createdAt: "desc" }],

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

export class FeatureUsageUnavailableError extends Error {
  constructor() {
    super("The requested usage feature is not included in the active plan.");
    this.name = "FeatureUsageUnavailableError";
  }
}

export class FeatureUsageCapacityError extends Error {
  constructor(
    readonly capacity: {
      featureCode: string;
      currentUsage: number;
      limit: number | null;
      remaining: number | null;
      requested: number;
    }
  ) {
    super("The usage limit has been reached.");
    this.name = "FeatureUsageCapacityError";
  }
}

/**
 * Add metered usage under a tenant/feature advisory lock. Use this for both
 * durable charges and temporary reservations that are released on failure.
 */
export async function reserveFeatureUsageInTransaction(
  tx: Prisma.TransactionClient,
  tenantId: string,
  featureCode: string,
  amount: number,
  enforceLimit = true
) {
  if (!Number.isInteger(amount) || amount <= 0) {
    throw new Error("Usage amount must be a positive integer.");
  }

  const lockKey = `metered-usage:${tenantId}:${featureCode}`;
  // pg_advisory_xact_lock returns PostgreSQL `void`; execute it without
  // asking Prisma's pg adapter to decode a result column.
  await tx.$executeRawUnsafe(
    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
    lockKey
  );

  const { subscription, planFeature } = await getFeatureAccessInfo(
    tenantId,
    featureCode,
    tx
  );
  if (!subscription || !planFeature) throw new FeatureUsageUnavailableError();

  const feature = planFeature.feature;
  if (feature.type !== "limit" || feature.aggregationType !== "sum") {
    throw new Error(
      `Feature '${featureCode}' does not use cumulative SUM usage.`
    );
  }

  let usageRecord =
    feature.resetCycle === "lifetime"
      ? await tx.subscriptionUsage.findFirst({
          where: {
            subscription_id: subscription.id,
            feature_id: planFeature.feature_id
          }
        })
      : await tx.subscriptionUsage.findUnique({
          where: {
            subscription_id_feature_id_period_start: {
              subscription_id: subscription.id,
              feature_id: planFeature.feature_id,
              period_start: subscription.currentPeriodStart
            }
          }
        });

  if (!usageRecord) {
    usageRecord = await tx.subscriptionUsage.upsert({
      where: {
        subscription_id_feature_id_period_start: {
          subscription_id: subscription.id,
          feature_id: planFeature.feature_id,
          period_start: subscription.currentPeriodStart
        }
      },
      update: { period_end: subscription.currentPeriodEnd },
      create: {
        subscription_id: subscription.id,
        feature_id: planFeature.feature_id,
        current_usage: 0,
        period_start: subscription.currentPeriodStart,
        period_end: subscription.currentPeriodEnd
      }
    });
  }

  const limit = planFeature.limit_value;
  const remaining =
    limit === null
      ? null
      : Math.max(0, limit - usageRecord.current_usage);
  if (
    enforceLimit &&
    limit !== null &&
    usageRecord.current_usage + amount > limit
  ) {
    throw new FeatureUsageCapacityError({
      featureCode,
      currentUsage: usageRecord.current_usage,
      limit,
      remaining,
      requested: amount
    });
  }

  await tx.subscriptionUsage.update({
    where: { id: usageRecord.id },
    data: { current_usage: { increment: amount } }
  });

  return {
    usageRecordId: usageRecord.id,
    currentUsage: usageRecord.current_usage + amount,
    limit,
    remaining: limit === null ? null : Math.max(0, limit - usageRecord.current_usage - amount)
  };
}

export async function releaseFeatureUsageInTransaction(
  tx: Prisma.TransactionClient,
  tenantId: string,
  featureCode: string,
  amount: number,
  usageRecordId?: string
) {
  if (!Number.isInteger(amount) || amount <= 0) return;

  const lockKey = `metered-usage:${tenantId}:${featureCode}`;
  // pg_advisory_xact_lock returns PostgreSQL `void`; execute it without
  // asking Prisma's pg adapter to decode a result column.
  await tx.$executeRawUnsafe(
    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
    lockKey
  );

  // Refund the original allocation, even after subscription/period replacement.
  if (usageRecordId) {
    await tx.subscriptionUsage.updateMany({ where: {
      id: usageRecordId, feature: { code: featureCode },
      subscription: { tenantId }, current_usage: { gte: amount }
    }, data: { current_usage: { decrement: amount } } });
    return;
  }
  const { subscription, planFeature } = await getFeatureAccessInfo(
    tenantId,
    featureCode,
    tx
  );
  if (!subscription || !planFeature) return;

  const usageRecord = usageRecordId
    ? await tx.subscriptionUsage.findFirst({
        where: {
          id: usageRecordId,
          subscription_id: subscription.id,
          feature_id: planFeature.feature_id
        }
      })
    : planFeature.feature.resetCycle === "lifetime"
      ? await tx.subscriptionUsage.findFirst({
          where: {
            subscription_id: subscription.id,
            feature_id: planFeature.feature_id
          }
        })
      : await tx.subscriptionUsage.findUnique({
          where: {
            subscription_id_feature_id_period_start: {
              subscription_id: subscription.id,
              feature_id: planFeature.feature_id,
              period_start: subscription.currentPeriodStart
            }
          }
        });
  if (!usageRecord) return;

  await tx.subscriptionUsage.updateMany({
    where: { id: usageRecord.id, current_usage: { gte: amount } },
    data: { current_usage: { decrement: amount } }
  });
}

/**
 * Resolve connector capacity inside the same transaction that creates or
 * reactivates a source. The caller must hold the tenant's source-capacity
 * advisory lock so two simultaneous requests cannot claim the last slot.
 */
export async function getConnectedDataSourceCapacityInTransaction(
  tx: Prisma.TransactionClient,
  tenantId: string
) {
  const currentUsage = await tx.data_sources.count({
    where: {
      tenant_id: tenantId,
      is_active: true,
      source_type: { in: [...COUNTED_CONNECTED_SOURCE_TYPES] }
    }
  });
  const [sourceAccess, integrationAccess] = await Promise.all([
    getFeatureAccessInfo(tenantId, "connected_data_sources", tx),
    getFeatureAccessInfo(tenantId, "data_integration", tx)
  ]);
  const { subscription, planFeature } = sourceAccess;
  const integrationEnabled = Boolean(
    subscription &&
      integrationAccess.subscription?.id === subscription.id &&
      integrationAccess.planFeature?.feature.type === "boolean"
  );

  if (!subscription || !planFeature || !integrationEnabled) {
    const limit = planFeature?.limit_value ?? 0;
    return {
      included: false as const,
      currentUsage,
      limit,
      remaining: 0,
      isUnlimited: false,
      isOverLimit: currentUsage > limit
    };
  }

  if (
    planFeature.feature.type !== "limit" ||
    planFeature.feature.aggregationType !== "max"
  ) {
    throw new Error(
      "connected_data_sources must use a MAX capacity entitlement."
    );
  }

  const isUnlimited = planFeature.limit_value === null;
  const limit = planFeature.limit_value;

  return {
    included: true as const,
    currentUsage,
    limit,
    remaining: isUnlimited
      ? null
      : Math.max(0, (limit ?? 0) - currentUsage),
    isUnlimited,
    isOverLimit: limit !== null && currentUsage > limit
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
  return prisma.$transaction(async (tx) => {
    try {
      const reservation = await reserveFeatureUsageInTransaction(
        tx,
        tenantId,
        featureCode,
        amount,
        featureCode === "document_extraction"
      );
      return tx.subscriptionUsage.findUnique({
        where: { id: reservation.usageRecordId }
      });
    } catch (error) {
      if (error instanceof FeatureUsageUnavailableError) return null;
      throw error;
    }
  });
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

    const usageRecord =

      feature.resetCycle === "lifetime"

        ? await prisma.subscriptionUsage.findFirst({

            where: {

              subscription_id: subscription.id,

              feature_id: feature.id

            }

          })

        : await prisma.subscriptionUsage.findUnique({

            where: {

              subscription_id_feature_id_period_start: {

                subscription_id: subscription.id,

                feature_id: feature.id,

                period_start: subscription.currentPeriodStart

              }

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
