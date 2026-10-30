export function isExpectedPlatformMeDenial(response, { expectedTenantFixture, apiUrl }) {
  if (!expectedTenantFixture || response.status !== 403 || response.method?.toUpperCase() !== 'GET') return false;
  try {
    const requestUrl = new URL(response.url);
    const apiOrigin = new URL(apiUrl).origin;
    return requestUrl.origin === apiOrigin && requestUrl.pathname === '/platform/me';
  } catch {
    return false;
  }
}
