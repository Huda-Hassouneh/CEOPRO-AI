const BRAND_ASSET_ROOT = '/assets/brands';

// Both files are served by the backend (GET /extraction/templates/{id}), so
// they always match what the importer reads.
export const DATA_TEMPLATE_OPTIONS = Object.freeze([
  { id: 'xlsx', labelKey: 'dataIngestion.templates.excel', icon: `${BRAND_ASSET_ROOT}/excel.svg`, filename: 'keel-sales-import-template.xlsx' },
  { id: 'csv', labelKey: 'dataIngestion.templates.csv', icon: `${BRAND_ASSET_ROOT}/csv.svg`, filename: 'keel-sales-import-template.csv' },
]);

export const getDataTemplateOption = (templateId) => DATA_TEMPLATE_OPTIONS.find(({ id }) => id === templateId);
