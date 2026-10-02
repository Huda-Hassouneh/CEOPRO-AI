import { basename } from "node:path";

export const MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024;

const ALLOWED_FILE_EXTENSIONS = new Set([".csv", ".xlsx", ".xlsm", ".pdf"]);

export type UploadValidationError =
  | "MISSING_FILE"
  | "INVALID_EXTENSION"
  | "INVALID_SIZE"
  | "FILE_TOO_LARGE";

export function getFileExtension(fileName: string): string {
  const normalized = fileName.toLowerCase();

  for (const extension of ALLOWED_FILE_EXTENSIONS) {
    if (normalized.endsWith(extension)) {
      return extension;
    }
  }

  return "";
}

export function safeUploadName(fileName: string): string {
  const safeBaseName = basename(fileName).replace(
    /[\x00-\x1f<>:"/\\|?*]+/g,
    "_"
  );

  return safeBaseName.slice(0, 255) || "upload";
}

export function validateExtractionUpload(
  file:
    | {
        originalname: string;
        size: number;
      }
    | undefined
): UploadValidationError | null {
  if (!file) {
    return "MISSING_FILE";
  }

  if (!getFileExtension(file.originalname)) {
    return "INVALID_EXTENSION";
  }

  if (!Number.isFinite(file.size) || file.size <= 0) {
    return "INVALID_SIZE";
  }

  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return "FILE_TOO_LARGE";
  }

  return null;
}
import {
  CreateDataSourcePayload,
  JsonObject,
  JsonValue,
  PERSISTENT_DATA_SOURCE_TYPES,
  PersistentDataSourceType
} from "../types/dataconnection.types.js";

type ValidationResult =
  | {
      success: true;
      data: CreateDataSourcePayload;
    }
  | {
      success: false;
      message: string;
    };

const DEFAULT_SYNC_FREQUENCY_MINUTES = 1440;

const FORBIDDEN_SECRET_KEYS = new Set([
  "password",
  "passwd",
  "secret",
  "client_secret",
  "clientsecret",
  "api_key",
  "apikey",
  "access_token",
  "accesstoken",
  "refresh_token",
  "refreshtoken",
  "authorization",
  "private_key",
  "privatekey",
  "connection_string",
  "connectionstring"
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPersistentSourceType(
  value: string
): value is PersistentDataSourceType {
  return (PERSISTENT_DATA_SOURCE_TYPES as readonly string[]).includes(value);
}

function normalizeKey(key: string): string {
  return key
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function containsForbiddenSecretKey(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some(containsForbiddenSecretKey);
  }

  if (!isRecord(value)) {
    return false;
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    if (FORBIDDEN_SECRET_KEYS.has(normalizeKey(key))) {
      return true;
    }

    if (containsForbiddenSecretKey(nestedValue)) {
      return true;
    }
  }

  return false;
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return true;
  }

  if (typeof value === "number") {
    return Number.isFinite(value);
  }

  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }

  if (isRecord(value)) {
    return Object.values(value).every(isJsonValue);
  }

  return false;
}

function validateMetadata(
  value: unknown
): { success: true; data: JsonObject } | { success: false; message: string } {
  if (value === undefined) {
    return {
      success: true,
      data: {}
    };
  }

  if (!isRecord(value)) {
    return {
      success: false,
      message: "metadata must be a JSON object."
    };
  }

  if (!isJsonValue(value)) {
    return {
      success: false,
      message: "metadata must contain only valid JSON values."
    };
  }

  if (containsForbiddenSecretKey(value)) {
    return {
      success: false,
      message:
        "Credentials, passwords, tokens, API keys, connection strings, and secrets must not be stored in metadata."
    };
  }

  return {
    success: true,
    data: value as JsonObject
  };
}

export function validateCreateDataSource(value: unknown): ValidationResult {
  if (!isRecord(value)) {
    return {
      success: false,
      message: "Request body must be an object."
    };
  }

  const rawName = value.name;

  if (typeof rawName !== "string" || rawName.trim().length === 0) {
    return {
      success: false,
      message: "name is required."
    };
  }

  const name = rawName.trim();

  /*
   * data_sources.source_name is VARCHAR(100)
   * in your current schema.
   */
  if (name.length > 100) {
    return {
      success: false,
      message: "name must not exceed 100 characters."
    };
  }

  if (typeof value.sourceType !== "string") {
    return {
      success: false,
      message: "sourceType is required."
    };
  }

  const sourceType = value.sourceType.trim().toLowerCase();

  if (!isPersistentSourceType(sourceType)) {
    return {
      success: false,
      message: `Unsupported sourceType. Supported values are: ${PERSISTENT_DATA_SOURCE_TYPES.join(", ")}.`
    };
  }

  let syncFrequencyMinutes = DEFAULT_SYNC_FREQUENCY_MINUTES;

  if (value.syncFrequencyMinutes !== undefined) {
    if (
      typeof value.syncFrequencyMinutes !== "number" ||
      !Number.isInteger(value.syncFrequencyMinutes) ||
      value.syncFrequencyMinutes <= 0
    ) {
      return {
        success: false,
        message: "syncFrequencyMinutes must be a positive integer."
      };
    }

    /*
     * PostgreSQL INT maximum.
     * The specification does not define
     * a business-specific upper limit.
     */
    if (value.syncFrequencyMinutes > 2_147_483_647) {
      return {
        success: false,
        message:
          "syncFrequencyMinutes exceeds the supported database integer range."
      };
    }

    syncFrequencyMinutes = value.syncFrequencyMinutes;
  }

  const metadataResult = validateMetadata(value.metadata);

  if (!metadataResult.success) {
    return metadataResult;
  }

  return {
    success: true,
    data: {
      name,
      sourceType,
      syncFrequencyMinutes,
      metadata: metadataResult.data
    }
  };
}
