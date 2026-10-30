import httpClient from '../../../shared/lib/httpClient.js';
import {useAuthStore} from '../../auth/store/authStore.js';
const pendingUploadKeys=new WeakMap();
import { getDataTemplateOption } from '../config/dataTemplateOptions.js';

// The frontend's own static template files (public/assets/templates/*)
// were a generic "Field,Value,Date,Notes" placeholder that never matched
// what backend/src/ai/routers/extraction.py's upload pipeline actually
// parses (product_name/quantity/unit_price/currency/transaction_date/...,
// backend/templates/apex_sales_import_v1.csv) - a user who
// downloaded and filled in the old placeholder would have every row
// rejected by the real importer. csv/xlsx now come from the real, canonical
// GET /extraction/templates/{fmt}. There is no PDF template (no approved
// PDF template exists) - DATA_TEMPLATE_OPTIONS only ever lists csv/xlsx,
// but PDF file upload/extraction itself (see backend/templates/README.md's
// own "PDF" section) is unaffected and stays fully supported.
export const ingestionApi = Object.freeze({
  previewBusinessImport:async(file,kind)=>{const data=new FormData();data.append('file',file);return (await httpClient.post('/extraction/structured-imports/preview',data,{params:{kind},headers:{'Idempotency-Key':crypto.randomUUID(),'Content-Type':undefined}})).data;},
  reviewBusinessImport:async(_kind,id,choices)=>(await httpClient.post(`/extraction/structured-imports/${id}/review`,{choices})).data,
  confirmBusinessImport:async(_kind,id,choices,reviewHash)=>(await httpClient.post(`/extraction/structured-imports/${id}/confirm`,{choices,reviewHash})).data,
  searchImportProducts:async(search)=>(await httpClient.get('/extraction/structured-imports/products',{params:{search}})).data.products,
  downloadTemplate: async (templateId) => {
    const template = getDataTemplateOption(templateId);
    if (!template) return { url: '', filename: '' };

    const response = await httpClient.get(`/extraction/templates/${templateId}`, { responseType: 'blob' });
    return { url: URL.createObjectURL(response.data), filename: template.filename };
  },

  // The real backend.upload pipeline (extraction/ingestion_pipeline.py)
  // takes one file per call - uploads sequentially so one bad file's
  // error doesn't abort the rest, and reports per-file outcomes rather
  // than a single pass/fail for the whole batch.
  prepareFiles: async (files) => {
    const results = [];
    for (const file of files) {
      try {
        const tenant=useAuthStore.getState().tenantId;
        const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(b=>b.toString(16).padStart(2,'0')).join('');
        const identity=`keel.upload.${tenant}.${digest}.${file.name}`;
        const storage=globalThis.sessionStorage;
        const key=storage?.getItem(identity)||pendingUploadKeys.get(file)||crypto.randomUUID();storage?.setItem(identity,key);pendingUploadKeys.set(file,key);
        const formData = new FormData();
        formData.append('file', file);
        const response = await httpClient.post('/extraction/upload', formData, { headers: { 'Content-Type': undefined, 'Idempotency-Key':key } });
        storage?.removeItem(identity);pendingUploadKeys.delete(file);
        results.push({ name: file.name, size: file.size, status: 'uploaded', summary: response.data });
      } catch (error) {
        results.push({ name: file.name, size: file.size, status: 'failed', error: error?.response?.data?.detail || error.message });
      }
    }
    return { files: results, uploaded: results.some((result) => result.status === 'uploaded') };
  },
});
