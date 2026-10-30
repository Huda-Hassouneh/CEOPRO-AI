import httpClient from '../../../shared/lib/httpClient.js';

export const importDraftsApi = Object.freeze({
  list: async ({ limit = 10, offset = 0, category } = {}) => (await httpClient.get('/extraction/import-drafts', {
    params: { limit, offset, ...(category ? { category } : {}) },
  })).data,
  detail: async (batchId, revisionId) => (await httpClient.get(
    revisionId
      ? `/extraction/import-drafts/${encodeURIComponent(batchId)}/revisions/${encodeURIComponent(revisionId)}`
      : `/extraction/import-drafts/${encodeURIComponent(batchId)}`,
  )).data,
  revisions: async (batchId) => (await httpClient.get(
    `/extraction/import-drafts/${encodeURIComponent(batchId)}/revisions`,
  )).data,
  reviews: async (batchId, revisionId) => (await httpClient.get(
    `/extraction/import-drafts/${encodeURIComponent(batchId)}/reviews`,
    { params: revisionId ? { revision_id: revisionId } : {} },
  )).data,
  decide: async (batchId, decision) => (await httpClient.post(
    `/extraction/import-drafts/${encodeURIComponent(batchId)}/reviews`,
    decision,
  )).data,
});

export function describeImportApiError(error, t) {
  const status = error?.response?.status;
  if (status === 401) return t('connectData.drafts.errors.unauthorized');
  if (status === 403) return t('connectData.drafts.errors.forbidden');
  if (status === 404) return t('connectData.drafts.errors.notFound');
  if (status === 409) return t('connectData.drafts.errors.conflict');
  if (status === 422) return t('connectData.drafts.errors.invalid');
  return t('connectData.drafts.errors.generic');
}

export function importDraftStateKey(state) {
  return `connectData.drafts.states.${String(state || 'draft').toLowerCase()}`;
}
