import { CreateFeatureDTO, UpdateFeatureDTO } from "../../../types/features.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { featureRepository } from "../repo/feature.repo.js";
import {
  AggregationType,
  FeatureType,
  ResetCycle
} from "../../../generated/prisma/enums.js";
import { documentsRepo } from "../repo/usage.repo.js";

function normalizeFeatureSemantics<
  T extends CreateFeatureDTO | UpdateFeatureDTO
>(data: T): T {
  if (data.type === FeatureType.boolean) {
    return {
      ...data,
      unit: null,
      unit_ar: null,
      aggregationType: AggregationType.sum,
      resetCycle: ResetCycle.lifetime
    } as T;
  }

  if (data.type === FeatureType.limit || data.aggregationType) {
    const aggregationType = data.aggregationType ?? AggregationType.sum;
    return {
      ...data,
      aggregationType,
      resetCycle:
        aggregationType === AggregationType.max
          ? ResetCycle.lifetime
          : (data.resetCycle ?? ResetCycle.billing_period)
    } as T;
  }

  return data;
}

export const featureService = {
  createFeature: async (data: CreateFeatureDTO) => {
    const existing = await featureRepository.findByCode(data.code);
    if (existing) {
      throw new Error(ERROR_CODES.RESOURCE_ALREADY_EXISTS);
    }
    return featureRepository.create(normalizeFeatureSemantics(data));
  },

  getAllFeatures: async () => featureRepository.findAll(),

  getFeatureById: async (id: string) => {
    const feature = await featureRepository.findById(id);
    if (!feature) {
      throw new Error(ERROR_CODES.RESOURCE_NOT_FOUND);
    }
    return feature;
  },

  updateFeature: async (id: string, data: UpdateFeatureDTO) => {
    const existing = await featureService.getFeatureById(id);
    const normalized = normalizeFeatureSemantics({
      ...data,
      type: data.type ?? existing.type,
      aggregationType: data.aggregationType ?? existing.aggregationType,
      resetCycle: data.resetCycle ?? existing.resetCycle
    });
    return featureRepository.update(id, normalized);
  }
};
export const ragService = {
  fetchChunkDetails: async (tenantId: string, chunkId: string) => {
    const chunk = await documentsRepo.getChunkById(tenantId, chunkId);

    if (!chunk) {
      throw {
        code: "NOT_FOUND",
        message: "Citation chunk not found or access denied."
      };
    }

    return {
      chunk_id: chunk.chunk_id,
      text_content: chunk.chunk_text_content,
      file_name: chunk.rag_documents_metadata?.file_name || "Unknown File"
    };
  }
};
