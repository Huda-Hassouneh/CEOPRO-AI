const TEMPLATE_ASSET_ROOT = '/assets/templates';
const BRAND_ASSET_ROOT = '/assets/brands';

export const DATA_TEMPLATE_OPTIONS = Object.freeze([
  {
    id: 'xlsx',
    labelKey: 'dataIngestion.templates.excel',
    icon: `${BRAND_ASSET_ROOT}/excel.svg`,
    url: `${TEMPLATE_ASSET_ROOT}/ceopro-data-template.xlsx`,
    filename: 'ceopro-data-template.xlsx',
  },
  {
    id: 'csv',
    labelKey: 'dataIngestion.templates.csv',
    icon: `${BRAND_ASSET_ROOT}/csv.svg`,
    url: `${TEMPLATE_ASSET_ROOT}/ceopro-data-template.csv`,
    filename: 'ceopro-data-template.csv',
  },
  {
    id: 'pdf',
    labelKey: 'dataIngestion.templates.pdf',
    icon: `${BRAND_ASSET_ROOT}/pdf.svg`,
    url: `${TEMPLATE_ASSET_ROOT}/ceopro-data-template.pdf`,
    filename: 'ceopro-data-template.pdf',
  },
]);

export const getDataTemplateOption = (templateId) => DATA_TEMPLATE_OPTIONS.find(({ id }) => id === templateId);
