import { planFeatureRepository } from "../repo/plan-feature.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js"; // Adjust path as needed
import { LinkFeatureDTO } from "../../../types/features.js";
import { prisma } from "../../../config/database.js";

export const planFeatureService = {
  linkFeatureToPlan: async (data: LinkFeatureDTO) => {
    const existingLink = await planFeatureRepository.findByPlanAndFeature(
      data.plan_id,
      data.feature_id
    );

    if (existingLink) {
      throw new Error(ERROR_CODES.RESOURCE_ALREADY_EXISTS);
    }
    return planFeatureRepository.create(data);
  },

  getPlanFeatures: async (plan_id: string) => {
    return planFeatureRepository.getFeaturesByPlanId(plan_id);
  },

  unlinkFeatureFromPlan: async (
    planId: string,
    featureId: string
  ): Promise<"removed" | "missing" | "inUse"> =>
    prisma.$transaction(async (tx) => {
      // A subscription insert takes a key-share lock on its referenced plan.
      // Lock the plan before checking subscriber history to avoid an unlink race.
      await tx.$queryRaw`SELECT id FROM plans WHERE id = ${planId}::uuid FOR UPDATE`;
      const link = await tx.planFeature.findUnique({
        where: {
          plan_id_feature_id: { plan_id: planId, feature_id: featureId }
        }
      });
      if (!link) return "missing";
      const [subscriptions, quotes] = await Promise.all([
        tx.subscription.count({
          where: { OR: [{ planId }, { scheduledPlanId: planId }] }
        }),
        tx.customPlanQuote.count({ where: { createdPlanId: planId } })
      ]);
      if (subscriptions || quotes) return "inUse";
      await tx.planFeature.delete({
        where: {
          plan_id_feature_id: { plan_id: planId, feature_id: featureId }
        }
      });
      return "removed";
    }),

  updateFeatureLimits: async (
    plan_id: string,
    feature_id: string,
    limit_value: number | null
  ) => {
    const existingLink = await planFeatureRepository.findByPlanAndFeature(
      plan_id,
      feature_id
    );

    if (!existingLink) {
      throw new Error(ERROR_CODES.RESOURCE_NOT_FOUND);
    }
    return planFeatureRepository.updateLimits(plan_id, feature_id, limit_value);
  }
};
