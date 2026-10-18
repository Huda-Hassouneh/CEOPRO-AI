import { translateCurrent } from '../../../shared/lib/i18n.js';
import { getDataTemplateOption } from "../config/dataTemplateOptions.js";
import httpClient from "../../../shared/lib/httpClient.js";
import { confirmSalesImport } from "../utils/salesImportConfirmation.js";
export const ingestionApi = Object.freeze({
  previewBusinessImport: async (file, kind) => {
    const body = new FormData();
    body.append('file', file);
    const response = await httpClient.post(`/data-connection/imports/${encodeURIComponent(kind)}/preview`, body);
    return response?.data?.data;
  },
  reviewBusinessImport: async (kind, draftId, choices) => {
    const response = await httpClient.post(`/data-connection/imports/${encodeURIComponent(kind)}/previews/${encodeURIComponent(draftId)}/review`, { choices });
    return response?.data?.data;
  },
  confirmBusinessImport: async (kind, draftId, choices, reviewHash) => {
    const response = await httpClient.post(`/data-connection/imports/${encodeURIComponent(kind)}/previews/${encodeURIComponent(draftId)}/confirm`, { choices, reviewHash });
    const result = response?.data?.data;
    if (!result?.jobId || result.kind !== kind || !Number.isInteger(result.imported) || !Number.isInteger(result.updated)) {
      throw new Error(translateCurrent("interfaceCopy.importNotCommitted"));
    }
    return result;
  },
  searchImportProducts: async (query) => {
    const response = await httpClient.get('/data-connection/imports/products', { params: { q: query } });
    return response?.data?.data ?? [];
  },
  downloadProductReference: async () => {
    const response = await httpClient.get("/data-connection/templates/catalog.csv", { responseType: "blob" });
    return { url: URL.createObjectURL(response.data), filename: "ceopro_product_catalog.csv" };
  },
  listJobs: async () => {
    const response = await httpClient.get("/data-connection/jobs");
    return response?.data?.data;
  },
  getJob: async (jobId) => {
    const response = await httpClient.get(
      `/data-connection/jobs/${encodeURIComponent(jobId)}`
    );
    return response?.data?.data;
  },
  reviewStagingRows: async (jobId, params = {}) => {
    const response = await httpClient.get(
      `/data-connection/jobs/${encodeURIComponent(jobId)}/staging`,
      { params }
    );
    return response?.data?.data;
  },
  updateStagingRow: async (jobId, rowId, payload) => {
    const response = await httpClient.patch(
      `/data-connection/jobs/${encodeURIComponent(jobId)}/staging/${encodeURIComponent(rowId)}`,
      { payload }
    );
    return response?.data?.data;
  },
  retryJob: async (jobId) => {
    const response = await httpClient.post(
      `/data-connection/jobs/${encodeURIComponent(jobId)}/retry`
    );
    return response?.data?.data;
  },
  downloadTemplate: async (templateId) => {
    const template = getDataTemplateOption(templateId);
    if (!template) {
      throw new Error(translateCurrent("interfaceCopy.templateUnavailable"));
    }
    const kind = template.kind || 'sales';
    const format = template.format || template.id;
    const response = await httpClient.get(
      `/data-connection/templates/${kind}/${format}`,
      { responseType: "blob" }
    );
    return {
      url: URL.createObjectURL(response.data),
      filename: template.filename,
      preview: false
    };
  },

  prepareFiles: async (files, kind = 'sales') => {
    const uploadPromises = files.map(async (file, index) => {
      const formData = new FormData();
      formData.append("file", file);

      // If the backend returns 400 or 422, this will automatically throw an error
      const path = kind === 'sales' ? '/data-connection' : `/data-connection/imports/${kind}`;
      const response = await httpClient.post(path, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      const payload = response?.data?.data;
      if (kind === 'sales') confirmSalesImport(payload);
      const confirmed = kind === 'sales'
        ? typeof payload?.job_id === 'string' && payload.job_id_source === 'ceopro' && (payload.duplicate || payload.job_status === 'queued')
        : typeof payload?.jobId === 'string' && payload.kind === kind &&
          Number.isInteger(payload.imported) && Number.isInteger(payload.updated) && payload.imported + payload.updated > 0;
      if (!confirmed) throw new Error(translateCurrent("interfaceCopy.importJobUnconfirmed"));

      return {
        index,
        name: file.name,
        size: file.size,
        status: payload.duplicate ? "duplicate" : "success",
        imported: payload.imported ?? 0,
        updated: payload.updated ?? 0,
        extractionData: payload
      };
    });

    const settled = await Promise.allSettled(uploadPromises);
    const results = settled.map((result, index) =>
      result.status === "fulfilled"
        ? result.value
        : {
            index,
            name: files[index].name,
            size: files[index].size,
            status: "failed",
            error: result.reason
          }
    );
    const succeeded = results.filter((item) => item.status === "success");
    const duplicates = results.filter((item) => item.status === "duplicate");
    const failed = results.filter((item) => item.status === "failed");

    return {
      files: results,
      preview: false,
      uploaded: succeeded.length > 0,
      succeeded: succeeded.length,
      duplicates: duplicates.length,
      failed: failed.length
    };
  }
});
