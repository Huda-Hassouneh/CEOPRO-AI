import httpClient from '../../../shared/lib/httpClient.js';

export const trialJourneyPreviewEnabled = import.meta.env?.VITE_RECURRING_JOURNEY_PREVIEW_ENABLED === 'true';
export const validTrialOperation = (value) => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

export async function getTrialJourneyPreview(operationId, signal) {
  if (!validTrialOperation(operationId)) throw new Error('Exact operation UUID required');
  const { data } = await httpClient.get(`/billing/trial-journeys/${encodeURIComponent(operationId)}`, { signal });
  if (data.operation_id?.toLowerCase() !== operationId.toLowerCase()) throw new Error('Operation mismatch');
  return data;
}

export function trialPreviewQuery(tenantId, userId, operationId, enabled) {
  return {
    queryKey: ['trialJourneyPreview', tenantId, userId, operationId],
    queryFn: ({ signal }) => getTrialJourneyPreview(operationId, signal),
    enabled: enabled === true && Boolean(tenantId && userId) && validTrialOperation(operationId),
    retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: true,
  };
}
