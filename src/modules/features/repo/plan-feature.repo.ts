import { prisma } from "../../../config/database.js";
import { LinkFeatureDTO } from "../../../types/features.js";

export const planFeatureRepository = {
  create: async (data: LinkFeatureDTO) => {
    return prisma.planFeature.create({ data });
  },

  findByPlanAndFeature: async (plan_id: string, feature_id: string) => {
    return prisma.planFeature.findUnique({
      where: {
        plan_id_feature_id: { plan_id, feature_id } // Using the @@unique compound key
      }
    });
  },

  getFeaturesByPlanId: async (plan_id: string) => {
    return prisma.planFeature.findMany({
      where: { plan_id },
      include: { feature: true } // Joins the actual feature details
    });
  },

  updateLimits: async (
    plan_id: string,
    feature_id: string,
    limit_value: number | null
  ) => {
    return prisma.planFeature.update({
      where: {
        plan_id_feature_id: { plan_id, feature_id }
      },
      data: { limit_value }
    });
  }
};
export const featureRepository = {
  findFeatureById: async (feature_id: string) => {
    return prisma.feature.findUnique({
      where: {
        id: feature_id
      }
    });
  }
};
