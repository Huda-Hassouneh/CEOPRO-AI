import httpClient from '../../../shared/lib/httpClient.js';
import { validTrialOperation } from './trialJourneyApi.js';
export const trialConsentEnabled = import.meta.env?.VITE_RECURRING_CONSENT_ENABLED === 'true';
const path = (operation) => {
  if (!validTrialOperation(operation)) throw new Error('Exact operation UUID required');
  return `/billing/trial-journeys/${operation}/consent`;
};
export const trialConsentApi = {
  async prepare(operation, language, signal) {
    const { data } = await httpClient.get(`${path(operation)}/preparation`, { params: { language }, signal });
    if (data.operation_id?.toLowerCase() !== operation.toLowerCase()) throw new Error('Operation mismatch');
    return data;
  },
  async present(operation, language) {
    return (await httpClient.post(`${path(operation)}/present`, { language })).data;
  },
  async accept(operation, language, presentation, checked) {
    if (checked !== true) throw new Error('Unchecked consent');
    return (await httpClient.post(`${path(operation)}/accept`, {
      language, presentation_id: presentation.presentation_id, challenge: presentation.challenge, checked,
    })).data;
  },
  async withdraw(operation, presentation) {
    return (await httpClient.post(`${path(operation)}/withdraw`, { presentation_id: presentation.presentation_id })).data;
  },
};
