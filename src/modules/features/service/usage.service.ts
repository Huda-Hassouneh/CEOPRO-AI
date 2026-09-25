import { documentsRepo, usageRepository } from "../repo/usage.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { getCurrentCapacityUsage } from "./capacity.service.js";

export const usageService = {
  getTenantUsageDashboard: async (tenantId: string) => {
    const subscription =
      await usageRepository.getCurrentUsageByTenant(tenantId);

    if (!subscription) {
      throw new Error(ERROR_CODES.SUBSCRIPTION_NOT_FOUND);
    }

    const entitlements = await Promise.all(
      subscription.plan.planFeatures.map(async (pf: any) => {
        const featureCode = pf.feature.code;
        const limit = pf.limit_value;
        let currentUsage = 0;

        if (
          pf.feature.type === "limit" &&
          pf.feature.aggregationType === "max"
        ) {
          currentUsage = await getCurrentCapacityUsage(tenantId, featureCode);
        } else if (
          pf.feature.type === "limit" &&
          pf.feature.aggregationType === "sum"
        ) {
          const usageRecord = subscription.subscriptionUsages.find(
            (su: any) => su.feature_id === pf.feature_id
          );
          currentUsage = usageRecord ? usageRecord.current_usage : 0;
        }

        const remaining =
          pf.feature.type !== "limit" || limit === null
            ? null
            : Math.max(0, limit - currentUsage);

        return {
          feature_code: featureCode,
          name: pf.feature.name,
          name_ar: pf.feature.name_ar,
          description: pf.feature.description,
          description_ar: pf.feature.description_ar,
          type: pf.feature.type,
          limit,
          current_usage: currentUsage,
          remaining,
          is_unlimited: pf.feature.type !== "limit" || limit === null,
          is_exceeded:
            pf.feature.type === "limit" &&
            limit !== null &&
            currentUsage >= limit,
          unit: pf.feature.unit,
          unit_ar: pf.feature.unit_ar,
          aggregation_type: pf.feature.aggregationType,
          reset_cycle: pf.feature.resetCycle
        };
      })
    );

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
