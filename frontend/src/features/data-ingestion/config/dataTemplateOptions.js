const BRAND_ASSET_ROOT = '/assets/brands';

export const DATA_TEMPLATE_OPTIONS = Object.freeze([
  {
    id: 'xlsx',
    labelKey: 'dataIngestion.templates.excel',
    icon: `${BRAND_ASSET_ROOT}/excel.svg`,
    filename: 'ceopro_sales_transaction_import_v1.xlsx',
  },
  {
    id: 'csv',
    labelKey: 'dataIngestion.templates.csv',
    icon: `${BRAND_ASSET_ROOT}/csv.svg`,
    filename: 'ceopro_sales_transaction_import_v1.csv',
  },
]);

const structuredTemplates = (kind) => [
  { id: `${kind}_xlsx`, kind, format: 'xlsx', labelKey: 'dataIngestion.templates.excel', icon: `${BRAND_ASSET_ROOT}/excel.svg`, filename: `ceopro_${kind}_import_v1.xlsx` },
  { id: `${kind}_csv`, kind, format: 'csv', labelKey: 'dataIngestion.templates.csv', icon: `${BRAND_ASSET_ROOT}/csv.svg`, filename: `ceopro_${kind}_import_v1.csv` },
];

export const getDataTemplateOptions = (kind = 'sales') =>
  kind === 'sales' ? DATA_TEMPLATE_OPTIONS : structuredTemplates(kind);

export const getDataTemplateOption = (templateId) =>
  [...DATA_TEMPLATE_OPTIONS, ...structuredTemplates('invoices'), ...structuredTemplates('inventory')]
    .find(({ id }) => id === templateId);
