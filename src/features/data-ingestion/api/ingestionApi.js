import { getDataTemplateOption } from '../config/dataTemplateOptions.js';

export const ingestionApi = Object.freeze({
  listJobs: async () => ({ jobs: [], preview: true }),
  reviewStagingRows: async () => ({ rows: [], preview: true }),
  downloadTemplate: async (templateId) => {
    const template = getDataTemplateOption(templateId);
    return { url: template?.url || '', filename: template?.filename || '', preview: true };
  },
  prepareFiles: async (files) => ({
    files: files.map((file) => ({ name: file.name, size: file.size, status: 'ready' })),
    preview: true,
    uploaded: false,
  }),
});
