import { usageRepository } from "../repo/usage.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";

export const usageService = {
  getTenantUsageDashboard: async (tenantId: string) => {
    const subscription =
      await usageRepository.getCurrentUsageByTenant(tenantId);

    if (!subscription) {
      throw new Error(ERROR_CODES.SUBSCRIPTION_NOT_FOUND);
    }

    // Map the raw data into a clean entitlement dashboard object for the UI
    const entitlements = subscription.plan.planFeatures.map((pf: any) => {
      // Prisma uses the cleaner property names (code, type) based on your schema @map
      const featureCode = pf.feature.code;
      const limit = pf.limit_value;

      // Find matching usage record for this billing cycle
      const usageRecord = subscription.subscriptionUsages.find(
        (su: any) => su.feature_id === pf.feature_id
      );

      const currentUsage = usageRecord ? usageRecord.current_usage : 0;

      return {
        feature_code: featureCode,
        name: pf.feature.name,
        type: pf.feature.type,
        limit: limit,
        current_usage: currentUsage,
        remaining:
          limit !== null ? Math.max(0, limit - currentUsage) : "unlimited",
        is_exceeded: limit !== null && currentUsage >= limit,

        // --- NEW FIELDS ADDED HERE ---
        unit: pf.feature.unit,
        // Map Prisma's camelCase back to snake_case for the JSON response
        aggregation_type: pf.feature.aggregationType,
        reset_cycle: pf.feature.resetCycle
      };
    });

    return {
      plan: {
        id: subscription.plan.id,
        name: subscription.plan.name,
        status: subscription.status,
        period_start: subscription.currentPeriodStart,
        period_end: subscription.currentPeriodEnd
      },
      entitlements
    };
  }
};
