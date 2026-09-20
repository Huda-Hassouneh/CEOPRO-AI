import { CreateFeatureDTO, UpdateFeatureDTO } from "../../../types/features.js";
import { prisma } from "../../../config/database.js";
import { FeatureCreateInput } from "../../../generated/prisma/models.js";

export const featureRepository = {
  create: async (data: FeatureCreateInput) => {
    return prisma.feature.create({ data });
  },

  findAll: async () => {
    return prisma.feature.findMany({
      orderBy: { created_at: "desc" }
    });
  },

  findById: async (id: string) => {
    return prisma.feature.findUnique({
      where: { id }
    });
  },

  findByCode: async (feature_code: string) => {
    return prisma.feature.findUnique({
      where: { code: feature_code }
    });
  },

  update: async (id: string, data: UpdateFeatureDTO) => {
    return prisma.feature.update({
      where: { id },
      data: data // Fixed this! It was previously hardcoded to an empty object {}
    });
  }
};
