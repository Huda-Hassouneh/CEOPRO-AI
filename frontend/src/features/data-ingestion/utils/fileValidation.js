export const MAX_UPLOAD_FILE_SIZE = 50 * 1024 * 1024;
export const ACCEPTED_UPLOAD_FILE_TYPES = '.pdf,.csv,.xlsx,.xls,.doc,.docx,.txt,.png,.jpg,.jpeg';
export const ALLOWED_UPLOAD_EXTENSIONS = /\.(pdf|csv|xlsx?|docx?|txt|png|jpe?g)$/i;
export const ALLOWED_IMAGE_EXTENSIONS = /\.(png|jpe?g)$/i;

// Data Connections manual extraction must match the Node upload contract.
export const MAX_BUSINESS_UPLOAD_FILE_SIZE = 10 * 1024 * 1024;
export const BUSINESS_UPLOAD_FILE_TYPES = '.pdf,.csv,.xlsx,.xlsm';
export const BUSINESS_UPLOAD_EXTENSIONS = /\.(pdf|csv|xlsx|xlsm)$/i;
export const STRUCTURED_BUSINESS_UPLOAD_FILE_TYPES = '.csv,.xlsx';
export const STRUCTURED_BUSINESS_UPLOAD_EXTENSIONS = /\.(csv|xlsx)$/i;

export function getInvalidBusinessUploadFile(files) {
  return Array.from(files).find(
    (file) =>
      !BUSINESS_UPLOAD_EXTENSIONS.test(file.name) ||
      file.size <= 0 ||
      file.size > MAX_BUSINESS_UPLOAD_FILE_SIZE
  ) || null;
}

export function getInvalidStructuredBusinessUploadFile(files) {
  return Array.from(files).find((file) =>
    !STRUCTURED_BUSINESS_UPLOAD_EXTENSIONS.test(file.name) ||
    file.size <= 0 || file.size > MAX_BUSINESS_UPLOAD_FILE_SIZE
  ) || null;
}

export function getInvalidUploadFile(files) {
  return Array.from(files).find((file) => !ALLOWED_UPLOAD_EXTENSIONS.test(file.name) || file.size > MAX_UPLOAD_FILE_SIZE) || null;
}

export function isSupportedUploadImage(file) {
  return Boolean(file?.type?.startsWith('image/')) && ALLOWED_IMAGE_EXTENSIONS.test(file.name);
}
