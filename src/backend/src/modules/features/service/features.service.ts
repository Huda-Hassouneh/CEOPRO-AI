import { CreateFeatureDTO, UpdateFeatureDTO } from "../../../types/features.js";
import { ERROR_CODES } from "../../../errors/error-codes.js"; // adjust path as needed
import { featureRepository } from "../repo/feature.repo.js";
import { FeatureCreateInput } from "../../../generated/prisma/models.js";

export const featureService = {
  createFeature: async (data: FeatureCreateInput) => {
    const existing = await featureRepository.findByCode(data.code);
    if (existing) {
      throw new Error(ERROR_CODES.RESOURCE_ALREADY_EXISTS);
    }
    return featureRepository.create(data);
  },

  getAllFeatures: async () => {
    return featureRepository.findAll();
  },

  getFeatureById: async (id: string) => {
    const feature = await featureRepository.findById(id);
    if (!feature) {
      throw new Error(ERROR_CODES.RESOURCE_NOT_FOUND);
    }
    return feature;
  },

  updateFeature: async (id: string, data: UpdateFeatureDTO) => {
    // Ensure it exists before updating
    await featureService.getFeatureById(id);
    return featureRepository.update(id, data);
  }
};
