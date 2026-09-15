import { unsupportedSettingsAction } from './settingsCapabilities.js';
const firstValue = (...values) => values.find((value) => value !== undefined && value !== null && value !== '') ?? '';

export const companyApi = {
  getCompany: async ({ user, companyId } = {}) => {
    const company = user?.company || user?.workspace || {};
    return {
      company: {
        id: company.id || company.tenant_id || companyId || null,
        name: firstValue(company.business_name, company.name, user?.companyName, user?.businessName),
        industry: firstValue(company.business_type, company.industry, user?.industry),
        businessSize: firstValue(company.businessSize, user?.businessSize),
        country: firstValue(company.country_code, company.country, user?.country),
        currency: firstValue(company.primary_currency, company.currency, user?.currency),
      },
      capabilities: { updateCompany: false },
    };
  },
  updateCompany: unsupportedSettingsAction,
};
