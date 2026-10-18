import httpClient from '../../../shared/lib/httpClient.js';

// Wraps the real backend endpoints - backend/src/ai/routers/settings.py's
// GET/PATCH /settings/company/search-scope, themselves a thin wrapper
// around company_geo_profile.py::get_tenant_search_scope/
// set_tenant_search_scope. This is what decides "which competitors count
// as relevant" for src/ai/pricing/competitor_classification.py - not a
// cosmetic preference.
export const searchScopeApi = {
  getSearchScope: async () => {
    const response = await httpClient.get('/settings/company/search-scope');
    return response.data;
  },

  // Owner/admin only server-side (a 403 from a non-admin caller surfaces
  // as a real error, not silently ignored) - same authorization the
  // company-wide currency/timezone settings already require.
  updateSearchScope: async ({ operatingCountries, latitude, longitude, city, searchScopeLevel, customRadiusKm } = {}) => {
    const response = await httpClient.patch('/settings/company/search-scope', {
      operating_countries: operatingCountries,
      latitude,
      longitude,
      city,
      search_scope_level: searchScopeLevel,
      custom_radius_km: customRadiusKm,
    });
    return response.data;
  },
};
