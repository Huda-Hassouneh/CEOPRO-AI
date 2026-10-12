import {
  PERSISTENT_DATA_SOURCE_TYPES,
  type PersistentDataSourceType
} from "../../../constants/data-source-types.js";

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
export type ClaimedIngestionJob = {
  tenant_id: string;
  job_id: string;
  processing_attempts: number;
};

export type ProcessedIngestionJob = {
  jobId: string;
  committed: number;
  quarantined: number;
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
  duplicate?: boolean;
  job_status?: string;
};
export { PERSISTENT_DATA_SOURCE_TYPES };
export type { PersistentDataSourceType };

export type jsonObject = {
  [key: string]: JsonValue;
};

export type CreateDataSourcePayload = {
  name: string;
  sourceType: PersistentDataSourceType;
  syncFrequencyMinutes?: number;
  sourceUrl?: string;
  metadata?: JsonObject;
};

export type CreateDataSourceInput = {
  tenantId: string;
  userId: string;
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
  sourceUrl: string | null;
  connectionStatus: "configured" | "disconnected";
  isActive: boolean;
  syncFrequencyMinutes: number | null;
  lastSyncedAt: string | null;
  createdAt: string | null;
  metadata: JsonObject;
};
