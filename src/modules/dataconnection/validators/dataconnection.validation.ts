// Backward-compatible exports. Keep source registration and file validation
// in one implementation so route and test callers enforce the same contract.
export {
  MAX_UPLOAD_SIZE_BYTES,
  getFileExtension,
  safeUploadName,
  validateCreateDataSource,
  validateExtractionUpload
} from "../types/dataconnection.validation.js";
export type { UploadValidationError } from "../types/dataconnection.validation.js";
