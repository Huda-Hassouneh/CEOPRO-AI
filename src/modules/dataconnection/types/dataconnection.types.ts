export type JsonObject = Record<string, any>;

export type ExtractionUploadInput = {
  tenantId: string;
  userId: string;
  authorization?: string;
  file: {
    originalname: string;
    mimetype: string;
    size: number;
    buffer: Buffer;
  };
};

export type ExtractionResult = {
  job_id: unknown;
  template_mode: unknown;
  is_template_compliant: unknown;
  rows_processed: unknown;
  rows_partial: unknown;
  rows_failed: unknown;
  data_loss_pct: unknown;
  header_coverage_ratio: unknown;
  row_outcomes: unknown;
  promotion: unknown;
  currency_resolution: unknown;
};
export const PERSISTENT_DATA_SOURCE_TYPES = [
  "shopify",
  "postgresql",
  "mysql",
  "sqlserver",
  "ga4",
  "website"
] as const;

export type PersistentDataSourceType =
  (typeof PERSISTENT_DATA_SOURCE_TYPES)[number];

export type JsonPrimitive = string | number | boolean | null;

export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export type jsonObject = {
  [key: string]: JsonValue;
};

export type CreateDataSourcePayload = {
  name: string;
  sourceType: PersistentDataSourceType;
  syncFrequencyMinutes?: number;
  metadata?: JsonObject;
};

export type CreateDataSourceInput = {
  tenantId: string;
  payload: CreateDataSourcePayload;
};

export type CreateDataSourceRepoInput = {
  tenantId: string;
  name: string;
  sourceType: PersistentDataSourceType;
  syncFrequencyMinutes: number;
  metadata: JsonObject;
};

export type DataSourceResponse = {
  id: string;
  name: string;
  sourceType: string;
  isActive: boolean;
  syncFrequencyMinutes: number | null;
  lastSyncedAt: string | null;
  createdAt: string | null;
  metadata: JsonObject;
};
