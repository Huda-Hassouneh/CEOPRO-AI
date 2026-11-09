import httpClient from '../../../shared/lib/httpClient.js';
import { validTrialOperation } from './trialJourneyApi.js';
export const subscriptionJourneyEnabled = import.meta.env?.VITE_RECURRING_JOURNEY_ENABLED === 'true';
const path = (operation) => {
  if (!validTrialOperation(operation)) throw new Error('Exact operation required');
  return `/billing/trial-journeys/${operation}`;
};
export function journeyRequestKey(tenant, actor, plan, period, storage = globalThis.sessionStorage) {
  const key = JSON.stringify(['keel.recurring.request', tenant, actor, plan, period]);
  let value = storage.getItem(key);
  if (!validTrialOperation(value)) {
    value = globalThis.crypto.randomUUID();
    storage.setItem(key, value);
  }
  return value;
}
export const subscriptionJourneyApi = {
  async start(plan, period, requestKey) {
    return (await httpClient.post('/billing/trial-journeys', { plan_key: plan, period_code: period, request_key: requestKey })).data;
  },
  async progress(operation, signal) {
    const { data } = await httpClient.get(`${path(operation)}/progress`, { signal });
    if (data.operation_id !== operation) throw new Error('Operation conflict');
    return data;
  },
  async advance(operation, language) {
    return (await httpClient.post(`${path(operation)}/advance`, { language })).data;
  },
  async cancel(operation) { return (await httpClient.post(`${path(operation)}/cancellation`, {})).data; },
  async cleanup(operation) { return (await httpClient.post(`${path(operation)}/cleanup`, {})).data; },
};
