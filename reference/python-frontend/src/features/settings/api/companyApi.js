import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/settings.py's
// GET/PATCH /settings/company. businessSize has no backend column
// (companies has no such field) - left undefined rather than fabricated;
// CompanySettings.jsx already falls back to "Not available" for any
// missing field.
function toCompany(body) {
  return {
    name: body.business_name || '',
    industry: body.business_type || '',
    businessSize: undefined,
    country: body.country_code || '',
    currency: body.primary_currency || '',
    industryKey: body.industry_key || '',
    description: body.business_description || '',
    website: body.website_url || '',
    onboardingCompletedAt: body.onboarding_completed_at || null,
    isDemo: Boolean(body.is_demo),
  };
}

export const companyApi = {
  getCompany: async () => {
    const response = await httpClient.get('/settings/company');
    return { company: toCompany(response.data), capabilities: { updateCompany: true } };
  },

  // Owner/admin only server-side (settings.py::update_company) - a 403
  // from a non-admin caller surfaces as a real error, not silently ignored.
  updateCompany: async ({ name, industry, country, currency, industryKey, description, website } = {}) => {
    const body = { business_name: name, business_type: industry, country_code: country, primary_currency: currency };
    if (industryKey !== undefined) body.industry_key = industryKey || null;
    if (description !== undefined) body.business_description = description || null;
    if (website !== undefined) body.website_url = website || null;
    const response = await httpClient.patch('/settings/company', Object.fromEntries(Object.entries(body).filter(([, v]) => v !== undefined)));
    return { persisted: true, company: toCompany(response.data) };
  },

  completeOnboarding: async () => toCompany((await httpClient.post('/settings/company/onboarding/complete')).data),

  // Explicit commercial Target Markets - backend/src/ai/routers/
  // settings.py's GET/PUT /settings/company/target-markets, themselves a
  // thin wrapper around company_target_markets.py. Deliberately a
  // SEPARATE concept from `country`/operating countries/search scope
  // above: which countries this tenant is registered/operates in vs.
  // which countries it explicitly wants to COMPETE IN. Never inferred
  // client-side either - this is only ever a direct reflection of what
  // the tenant typed and saved.
  //
  // Each entry is {market_type: 'COUNTRY'|'REGION'|'GLOBAL', country_code,
  // region_name} - the same structured shape the backend stores and
  // returns (company_target_markets.py's own contract), never a bare
  // country-code string.
  getTargetMarkets: async () => {
    const response = await httpClient.get('/settings/company/target-markets');
    return response.data.target_markets;
  },

  // Owner/admin only server-side - a 403 from a non-admin caller surfaces
  // as a real error, not silently ignored. A real replace/PUT: the whole
  // declared list is sent every time, matching set_tenant_target_markets()'s
  // own replace semantics (an empty array is a valid, explicit "clear it").
  updateTargetMarkets: async (targetMarkets = []) => {
    const response = await httpClient.put('/settings/company/target-markets', {
      target_markets: targetMarkets,
    });
    return response.data.target_markets;
  },
};
