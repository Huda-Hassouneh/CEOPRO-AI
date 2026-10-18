import httpClient from '../../../shared/lib/httpClient.js';

const IMPORT_STATUS = { COMPLETED: 'completed', FAILED: 'failed', PROCESSING: 'processing', QUEUED: 'processing' };
const FILE_TYPE = { csv: 'csv', xlsx: 'xlsx', xlsm: 'xlsx', pdf: 'pdf' };
const FILE_UPLOAD_SOURCE = Object.freeze({ en: 'File upload', ar: 'رفع ملف' });

// The fields every sales record maps to (backend template_contract.py).
export const SALES_FIELDS = Object.freeze([
  { key: 'product_name', required: true },
  { key: 'quantity', required: true },
  { key: 'unit_price', required: true },
  { key: 'currency', required: true },
  { key: 'transaction_date', required: true },
  { key: 'invoice_id', required: false },
  { key: 'discount_pct', required: false },
]);

// GET /extraction/imports - the company's real file-import history, newest first.
export function mapRecentImports(response) {
  return (response?.imports || []).map((item) => ({
    id: item.job_id,
    date: item.created_at,
    source: FILE_UPLOAD_SOURCE,
    name: item.file_name,
    type: FILE_TYPE[item.file_type] || 'connection',
    status: IMPORT_STATUS[item.status] || 'needsAttention',
  }));
}

// {their_field: our_field} from the form's {our_field: their_field}.
function toFieldMapping(mapping) {
  return Object.fromEntries(Object.entries(mapping).filter(([, theirs]) => theirs && theirs.trim()).map(([ours, theirs]) => [theirs.trim(), ours]));
}

export const dataConnectionsApi = Object.freeze({
  list: async () => {
    const [imports, sources] = await Promise.all([httpClient.get('/extraction/imports'), httpClient.get('/onboarding/sources')]);
    return { connectedSources: sources.data.sources, recentImports: mapRecentImports(imports.data) };
  },
  // POST /onboarding/connect/api - the company's own POS/ERP/e-commerce REST API.
  connectApi: async (form) => (await httpClient.post('/onboarding/connect/api', {
    source_name: form.name.trim(),
    base_url: form.baseUrl.trim(),
    records_path: form.recordsPath.trim() || undefined,
    page_param: form.pageParam.trim() || undefined,
    auth_header: form.authHeader.trim() || undefined,
    auth_scheme: form.authScheme.trim(),
    credentials: form.token ? { token: form.token } : undefined,
    field_mapping: toFieldMapping(form.mapping),
    sync_frequency_minutes: Number(form.frequency),
  })).data,
  // POST /onboarding/connect/database - read-only access to the company's own Postgres database.
  connectDatabase: async (form) => (await httpClient.post('/onboarding/connect/database', {
    source_name: form.name.trim(),
    host: form.host.trim(),
    port: Number(form.port),
    dbname: form.dbname.trim(),
    query: form.query.trim(),
    credentials: { user: form.user.trim(), password: form.password },
    field_mapping: toFieldMapping(form.mapping),
    sync_frequency_minutes: Number(form.frequency),
  })).data,
  syncNow: async (sourceId) => (await httpClient.post(`/onboarding/sources/${encodeURIComponent(sourceId)}/sync`)).data,
  disconnect: async (sourceId) => (await httpClient.delete(`/onboarding/sources/${encodeURIComponent(sourceId)}`)).data,
});
