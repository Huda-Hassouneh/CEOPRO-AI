import {
  FeatureType,
  AggregationType,
  ResetCycle
} from "../generated/prisma/enums.js";

export interface CreateFeatureDTO {
  code: string;
  name: string;
  name_ar: string;
  description?: string | null;
  description_ar?: string | null;
  type: FeatureType;
  unit?: string | null;
  unit_ar?: string | null;
  aggregationType?: AggregationType;
  resetCycle?: ResetCycle;
}

export interface UpdateFeatureDTO {
  name?: string;
  name_ar?: string;
  description?: string | null;
  description_ar?: string | null;
  type?: FeatureType;
  unit?: string | null;
  unit_ar?: string | null;
  aggregationType?: AggregationType;
  resetCycle?: ResetCycle;
}

export interface LinkFeatureDTO {
  plan_id: string;
  feature_id: string;
  limit_value?: number | null;
}
