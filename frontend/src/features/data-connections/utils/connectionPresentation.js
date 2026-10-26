import {getApiError} from '../../billing/api/customerBillingApi.js';
const getApiErrorMessage=(error,t)=>getApiError(error).message||t('common.error');
import { formatImportIssue } from '../../data-ingestion/utils/importIssueMessage.js';

const statusKeys = new Set(['connected', 'completed', 'queued', 'extracting', 'processing',
  'needsAttention', 'failed', 'notsynced', 'configured', 'synced', 'paused', 'disconnected']);

export function normalizeConnectionStatus(status) {
  const value = String(status || '').toLowerCase();
  const key = value === 'needsattention' ? 'needsAttention' : value;
  return statusKeys.has(key) ? key : 'unknown';
}

export const connectionStatusLabel = (status, t) => t(`connectData.statuses.${normalizeConnectionStatus(status)}`);

/** API enums are UI copy; source names, file names and imported values are not. */
export function activityTypeLabel(type, t) {
  const key = String(type || '').toLowerCase().replace(/[ _-]/g, '');
  const supported = new Set(['csv', 'pdf', 'xlsx', 'excel', 'file', 'connection', 'website', 'analytics', 'businesssystem']);
  return t(`connectData.fileTypes.${supported.has(key) ? key : 'unknown'}`);
}

export function localizedConnectionValue(value, locale) {
  return value && typeof value === 'object' ? value[locale] || value.en || value.ar || '' : value;
}

export function activityName(item, locale, t) {
  const name = localizedConnectionValue(item.name, locale);
  const type = String(item.type || '').toLowerCase();
  return !['file', 'csv', 'pdf', 'xlsx', 'excel'].includes(type) && typeof name === 'string' && name.startsWith('Sync - ')
    ? t('connectData.activity.syncName', { name: name.slice(7) }) : name;
}

const categoryKeys = Object.freeze({
  Sales: 'sales', Products: 'products', Inventory: 'inventory', Invoices: 'invoices',
  Pricing: 'pricing', 'Website traffic': 'traffic', 'Customer activity': 'customers', 'General Data': 'general',
});

export function dataCategoryLabel(value, locale, t) {
  const name = typeof value === 'object' && value ? value.en : value;
  const key = Object.hasOwn(categoryKeys, name) ? categoryKeys[name] : null;
  return key ? t(`connectData.categories.${key}`) : localizedConnectionValue(value, locale);
}

export function importSheetLabel(value, t) {
  const sheets = { Sales: 'sales', Invoices: 'invoices', 'Invoice Items': 'invoiceItems', Inventory: 'inventory' };
  const key = Object.hasOwn(sheets, value) ? sheets[value] : null;
  return key ? t(`connectData.review.sheetNames.${key}`) : value;
}

export function storeErrorMessage(error, t) {
  const code = getApiError(error).code;
  const key = `storeConnection.errors.${/^(?:STORE_[A-Z_]+|INVALID_STORE_URL|CONNECTOR_NOT_CONFIGURED)$/.test(code || '') ? code : 'STORE_SERVICE_UNAVAILABLE'}`;
  const message = t(key);
  return message && message !== key ? message : t('storeConnection.errors.STORE_SERVICE_UNAVAILABLE');
}

export function dataConnectionErrorMessage(error, t) {
  const api = getApiError(error);
  if (/^(?:STORE_|INVALID_STORE_URL$|CONNECTOR_NOT_CONFIGURED$)/.test(api.code || '')) return storeErrorMessage(error, t);
  const issue = formatImportIssue(api.details?.message || api.message || error?.message, t, { fallback: '' });
  if (issue) return issue;
  // Prefer the stable API code to a server-owned English sentence.
  const key = `apiErrors.${api.code}`;
  if (api.code && t(key) !== key) return t(key);
  return getApiErrorMessage({ response: { status: api.status }, request: error?.request }, t);
}

export function jobErrorMessage(message, t) {
  const text = String(message || '');
  if (!text) return '';
  const summary = text.match(/^(\d+) invalid row\(s\); (\d+) partial row\(s\) require review\.?$/i);
  if (summary) return t('connectData.job.reviewSummary', { invalid: summary[1], partial: summary[2] });
  const code = text.match(/^([A-Z][A-Z_]+)(?::|$)/)?.[1];
  if (code?.startsWith('STORE_')) return storeErrorMessage({ code }, t);
  if (code) {
    const key = `connectData.job.errors.${code}`;
    if (t(key) !== key) return t(key);
  }
  return formatImportIssue(text, t, { fallback: t('connectData.job.unknownError') });
}

export function rowValidationMessage(errors, t) {
  if (!errors) return '—';
  let values = errors;
  if (typeof errors === 'string') {
    try { values = JSON.parse(errors); } catch { return jobErrorMessage(errors, t); }
  }
  if (values && typeof values === 'object') {
    return Object.entries(values).map(([field, message]) => {
      const labelKey = `connectData.job.fields.${field}`;
      const label = t(labelKey) !== labelKey ? t(labelKey) : field;
      return `${label}: ${jobErrorMessage(typeof message === 'object' ? message?.message : message, t)}`;
    }).join(' · ');
  }
  return jobErrorMessage(values, t);
}
