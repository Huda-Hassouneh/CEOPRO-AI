import { getDataTemplateOption } from "../config/dataTemplateOptions.js";
import httpClient from "../../../shared/lib/httpClient.js";
export const ingestionApi = Object.freeze({
  listJobs: async () => ({ jobs: [], preview: true }),
  reviewStagingRows: async () => ({ rows: [], preview: true }),
  downloadTemplate: async (templateId) => {
    const template = getDataTemplateOption(templateId);
    return {
      url: template?.url || "",
      filename: template?.filename || "",
      preview: true
    };
  },

  prepareFiles: async (files) => {
    const uploadPromises = files.map(async (file) => {
      const formData = new FormData();
      formData.append("file", file);

      // If the backend returns 400 or 422, this will automatically throw an error
      const response = await httpClient.post("/data-connection", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });

      return {
        name: file.name,
        size: file.size,
        status: "success",
        extractionData: response.data.data
      };
    });

    // Wait for all uploads. If ANY fail, it throws to the UI immediately.
    const results = await Promise.all(uploadPromises);

    return {
      files: results,
      preview: false,
      uploaded: true
    };
  }
});
