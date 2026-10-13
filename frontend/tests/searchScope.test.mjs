import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { searchScopeApi } from '../src/features/market-intelligence/api/searchScopeApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// searchScopeApi wraps the real, mounted
// backend/src/ai/routers/settings.py GET/PATCH /settings/company/
// search-scope endpoints, themselves a thin wrapper around
// company_geo_profile.py::get_tenant_search_scope/set_tenant_search_scope
// - this test verifies the request/response shape actually matches what
// that backend router sends and expects, not a mocked assumption.

function withServer(handler) {
  return async (t) => {
    const server = http.createServer(handler);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const originalBaseURL = httpClient.defaults.baseURL;
    httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
    t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });
  };
}

test('searchScopeApi.getSearchScope returns the real stored profile shape', async (t) => {
  await withServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/settings/company/search-scope' && req.method === 'GET') {
      return res.end(JSON.stringify({
        country_code: 'JO', operating_countries: ['JO'], latitude: 31.9539, longitude: 35.9106,
        city: 'Amman', search_scope_level: 'CITY', default_search_radius_km: 25,
      }));
    }
    res.statusCode = 404;
    res.end('{}');
  })(t);

  const result = await searchScopeApi.getSearchScope();
  assert.equal(result.search_scope_level, 'CITY');
  assert.equal(result.default_search_radius_km, 25);
  assert.equal(result.city, 'Amman');
});

test('searchScopeApi.updateSearchScope sends the real snake_case request body and returns the updated profile', async (t) => {
  let received;
  await withServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/settings/company/search-scope' && req.method === 'PATCH') {
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('end', () => {
        received = JSON.parse(body);
        res.end(JSON.stringify({
          country_code: 'JO', operating_countries: [], latitude: null, longitude: null,
          city: null, search_scope_level: 'GLOBAL', default_search_radius_km: null,
        }));
      });
      return;
    }
    res.statusCode = 404;
    res.end('{}');
  })(t);

  const result = await searchScopeApi.updateSearchScope({ searchScopeLevel: 'GLOBAL' });
  assert.equal(received.search_scope_level, 'GLOBAL');
  assert.equal(received.custom_radius_km, undefined);
  assert.equal(result.search_scope_level, 'GLOBAL');
  assert.equal(result.default_search_radius_km, null);
});

test('searchScopeApi.updateSearchScope sends operating_countries and custom_radius_km when provided', async (t) => {
  let received;
  await withServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      received = JSON.parse(body);
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({
        country_code: 'JO', operating_countries: ['JO', 'AE'], latitude: null, longitude: null,
        city: null, search_scope_level: 'CUSTOM', default_search_radius_km: 40,
      }));
    });
  })(t);

  await searchScopeApi.updateSearchScope({
    operatingCountries: ['JO', 'AE'], searchScopeLevel: 'CUSTOM', customRadiusKm: 40,
  });
  assert.deepEqual(received.operating_countries, ['JO', 'AE']);
  assert.equal(received.custom_radius_km, 40);
  assert.equal(received.search_scope_level, 'CUSTOM');
});
