import { prisma } from "../../../config/database.js";

export const usageRepository = {
  // Fetch current usage for a specific tenant's active subscription
  getCurrentUsageByTenant: async (tenantId: string) => {
    const now = new Date();

    return prisma.subscription.findFirst({
      where: {
        tenantId: tenantId,
        status: "active"
      },
      include: {
        plan: {
          include: {
            planFeatures: {
              include: { feature: true }
            }
          }
        },
        subscriptionUsages: {
          where: {
            period_start: { lte: now },
            period_end: { gte: now }
          },
          include: { feature: true }
        }
      }
    });
  },

  increment: async (usageId: string) => {
    return prisma.subscriptionUsage.update({
      where: { id: usageId },
      data: { current_usage: { increment: 1 } }
    });
  }
};

export const incrementUsage = async (tenantId: string, featureCode: string) => {
  const now = new Date();

  // Find the current active usage record for this tenant and feature
  const usageRecord = await prisma.subscriptionUsage.findFirst({
    where: {
      subscription: {
        tenantId: tenantId,
        status: "active"
      },
      feature: {
        feature_code: featureCode
      },
      period_start: { lte: now },
      period_end: { gte: now }
    }
  });

  if (usageRecord) {
    await prisma.subscriptionUsage.update({
      where: { id: usageRecord.id },
      data: { current_usage: { increment: 1 } }
    });
  }
};
