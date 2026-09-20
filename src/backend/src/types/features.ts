import { prisma } from "../config/database.js";
import {
  FeatureType,
  AggregationType,
  ResetCycle
} from "../generated/prisma/enums.js";

export interface CreateFeatureDTO {
  code: string;
  name: string;
  description?: string;
  type: FeatureType;

  // --- NEW FIELDS ---
  unit?: string;
  aggregationType?: AggregationType; // Prisma uses camelCase because of the @map in schema
  resetCycle?: ResetCycle; // Prisma uses camelCase because of the @map in schema
}

export interface UpdateFeatureDTO {
  name?: string;
  description?: string;
  type?: FeatureType;

  // --- NEW FIELDS ---
  unit?: string;
  aggregationType?: AggregationType;
  resetCycle?: ResetCycle;
}
export interface LinkFeatureDTO {
  plan_id: string;
  feature_id: string;
  limit_value?: number | null;
}
