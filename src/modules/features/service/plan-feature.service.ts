import { planFeatureRepository } from "../repo/plan-feature.repo.js";
import { ERROR_CODES } from "../../../errors/error-codes.js"; // Adjust path as needed
import { LinkFeatureDTO } from "../../../types/features.js";

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
