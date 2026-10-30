export const ACCOUNTING_UNITS = ['request', 'record', 'page', 'input_token', 'output_token', 'cache_read_token', 'cache_write_token', 'image'];
export const RAG_SEARCH_PROVIDERS = ['google_cse', 'brave_search', 'tavily'];
export const emptyPrice = () => ({ budget_kind: 'data', provider: '', operation: 'search', unit: 'request', unit_cost_usd: '', safety_margin: '', charged_on_failure: true, cost_is_final: true, source: '', verified_at: '', reason: '' });
export function decimalText(value) {
  const text = String(value ?? '');
  const match = /^(\d+)(?:\.(\d+))?e([+-]?\d+)$/i.exec(text);
  if (!match) return text;
  const digits = match[1] + (match[2] || '');
  const point = match[1].length + parseInt(match[3], 10);
  if (point <= 0) return '0.' + '0'.repeat(-point) + digits;
  if (point >= digits.length) return digits + '0'.repeat(point - digits.length);
  return digits.slice(0, point) + '.' + digits.slice(point);
}
export function accountingRows(schedules = []) {
  const rank = row => row.budget_kind === 'data' && row.operation === 'search' && row.unit === 'request' && RAG_SEARCH_PROVIDERS.includes(row.provider) ? RAG_SEARCH_PROVIDERS.indexOf(row.provider) : 99;
  return [...schedules, ...RAG_SEARCH_PROVIDERS.filter(provider => !schedules.some(row => row.budget_kind === 'data' && row.provider === provider && row.operation === 'search' && row.unit === 'request'))
    .map(provider => ({ ...emptyPrice(), provider, unit_cost_usd: null }))].sort((a, b) => rank(a) - rank(b));
}
export function priceStatus(row) {
  if (row.unit_cost_usd == null || row.unit_cost_usd === '') return 'missing';
  if (/^0+(\.0+)?$/.test(decimalText(row.unit_cost_usd))) return 'zero';
  return row.cost_is_final ? 'configured' : 'nonFinal';
}
// Keep monetary strings all the way to Pydantic Decimal; never round via Number.
export function pricePayload(form) {
  const errors = {};
  for (const key of ['provider', 'operation', 'source', 'reason', 'verified_at']) if (!String(form[key] || '').trim()) errors[key] = true;
  if (!['data', 'ai'].includes(form.budget_kind)) errors.budget_kind = true;
  if (!ACCOUNTING_UNITS.includes(form.unit)) errors.unit = true;
  if (!/^\d{1,8}(\.\d{1,12})?$/.test(form.unit_cost_usd) || /^0*\d{9}/.test(form.unit_cost_usd)) errors.unit_cost_usd = true;
  if (form.safety_margin !== '' && !/^(?:[01](?:\.\d{1,4})?|2(?:\.0{1,4})?)$/.test(form.safety_margin)) errors.safety_margin = true;
  if (Object.keys(errors).length) return { errors };
  return { body: { ...form, provider: form.provider.trim(), operation: form.operation.trim(), source: form.source.trim(), reason: form.reason.trim(), safety_margin: form.safety_margin === '' ? null : form.safety_margin } };
}
