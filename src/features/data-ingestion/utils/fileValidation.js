export const MAX_UPLOAD_FILE_SIZE = 50 * 1024 * 1024;
export const ACCEPTED_UPLOAD_FILE_TYPES = '.pdf,.csv,.xlsx,.xls,.doc,.docx,.txt,.png,.jpg,.jpeg';
export const ALLOWED_UPLOAD_EXTENSIONS = /\.(pdf|csv|xlsx?|docx?|txt|png|jpe?g)$/i;
export const ALLOWED_IMAGE_EXTENSIONS = /\.(png|jpe?g)$/i;

export function getInvalidUploadFile(files) {
  return Array.from(files).find((file) => !ALLOWED_UPLOAD_EXTENSIONS.test(file.name) || file.size > MAX_UPLOAD_FILE_SIZE) || null;
}

export function isSupportedUploadImage(file) {
  return Boolean(file?.type?.startsWith('image/')) && ALLOWED_IMAGE_EXTENSIONS.test(file.name);
}
