export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type ExtractionUploadInput = {
  tenantId: string;
  userId: string;
  file: {
    originalname: string;
    mimetype: string;
    size: number;
    buffer: Buffer;
  };
};

export type ExtractionRowOutcome = {
  row_index: number;
  mode: string;
  parse_result?: { typed_fields: Record<string, unknown> } | null;
  field_errors: unknown[] | Record<string, unknown>;
  error?: string | null;
};

export type ExtractionResult = {
  job_id: string;
  job_id_source: "ceopro";
  file_name: string;
  detected_type: string;
  headers: string[];
  rows_processed: number;
  rows_partial: number;
  rows_failed: number;
  rows_truncated_to_limit: boolean | number;
  staged_row_count: number;
  template_mode: string;
  is_template_compliant: null;
  data_loss_pct: null;
  header_coverage_ratio: number;
  row_outcomes: ExtractionRowOutcome[];
  promotion: null;
  currency_resolution: null;
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
