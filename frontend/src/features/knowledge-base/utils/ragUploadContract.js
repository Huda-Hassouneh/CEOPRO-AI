export const RAG_MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
export const RAG_ACCEPTED_FILE_TYPES = '.txt,.md,.pdf,.docx,.xlsx';
export function getInvalidRagUploadFile(files) {
  return Array.from(files).find(file => !/\.(txt|md|pdf|docx|xlsx)$/i.test(file.name) || file.size <= 0 || file.size > RAG_MAX_UPLOAD_BYTES) || null;
}
export function documentStorageStatus(status, retrievalMode) {
  if (status === 'Stored' || (status === 'Processed' && retrievalMode === 'on_demand')) return 'stored';
  return ({Pending:'processing',Processed:'ready',Failed:'failed'})[status] || 'unknown';
}
