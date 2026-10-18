import { getApiError } from '../../../shared/lib/apiErrorCore.js';

function websiteError(code) {
  return Object.assign(new Error(code), { code });
}

export function normalizeWebsiteUrl(value) {
  try {
    if (typeof value !== 'string' || !value.trim() || value.trim().length > 2048) throw new Error();
    const url = new URL(value.trim());
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error();
    url.hash = '';
    url.pathname = url.pathname.replace(/\/+$/, '') || '/';
    const normalized = url.toString();
    return normalized.endsWith('/') ? normalized.slice(0, -1) : normalized;
  } catch {
    throw websiteError('INVALID_WEBSITE_URL');
  }
}

// Saved/configured is distinct from a website that has actually synchronized.
export async function saveWebsiteSource(value, api) {
  const url = normalizeWebsiteUrl(value);
  try {
    const source = await api.configureWebsite({ url });
    if (!source?.id || source.connectionStatus !== 'configured' || source.isActive === false) {
      throw websiteError('WEBSITE_SAVE_FAILED');
    }
    return { id: source.id, url: source.sourceUrl || url, status: 'configured' };
  } catch (error) {
    if (getApiError(error).code !== 'DUPLICATE_RESOURCE') throw error;
    // An earlier attempt may have saved successfully while the old UI reported
    // an error. Reuse only a matching active source returned by this tenant's API.
    try {
      const result = await api.list({});
      const source = result?.connectedSources?.find(item => {
        if (!item.id || item.type !== 'website' || item.isActive !== true || item.status === 'disconnected') return false;
        try { return normalizeWebsiteUrl(item.sourceUrl) === url; } catch { return false; }
      });
      if (source) return { id: source.id, url: source.sourceUrl, status: source.status === 'connected' ? 'connected' : 'configured' };
    } catch { /* Preserve the original error if recovery cannot verify a source. */ }
    throw error;
  }
}
