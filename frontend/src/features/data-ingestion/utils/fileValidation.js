// Real bug found live in first-customer E2E acceptance testing: these used
// to allow .xls/.doc/.docx/.txt/.png/.jpg client-side (matching what the
// dropzone's "Supported:" copy claimed), but the real backend endpoint
// these files go to (POST /extraction/upload, backend/src/ai/extraction/
// file_dispatch.py's own SUPPORTED_EXTENSIONS) only ever accepted
// .csv/.xlsx/.xlsm/.pdf - any of those other types passed client-side
// validation with no warning, only to be rejected by the server with a
// confusing error after the user had already picked a file the UI told
// them was supported. Narrowed to match SUPPORTED_EXTENSIONS exactly.
// Must match the backend's real limit (routers/extraction.py
// _MAX_UPLOAD_BYTES, MAX_UPLOAD_SIZE_BYTES default 10 MB). This used to be
// 50 MB, so an 11-50 MB file passed client-side validation and the copy
// promised it would work, then the server rejected it with a 413.
export const MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024;
export const ACCEPTED_UPLOAD_FILE_TYPES = '.pdf,.csv,.xlsx,.xlsm';
export const ALLOWED_UPLOAD_EXTENSIONS = /\.(pdf|csv|xlsx|xlsm)$/i;

export function getInvalidUploadFile(files) {
  return Array.from(files).find((file) => !ALLOWED_UPLOAD_EXTENSIONS.test(file.name) || file.size > MAX_UPLOAD_FILE_SIZE) || null;
}
