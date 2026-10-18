import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
const workerRequest = callback => COMPETITOR_AI_ACTIONS_ENABLED ? callback() : Promise.reject(Object.assign(new Error('Competitor worker integration is not connected'),{code:'NOT_IMPLEMENTED'}));
import httpClient from "../../../shared/lib/httpClient.js";
const data = response => response.data?.data ?? response.data;
export const competitorsApi = {
  list: async (_companyId, status = 'active') => { const response=await httpClient.get('/competitors', { params: { status } }); const rows=data(response); return Array.isArray(rows) ? { competitors:rows,...response.data?.meta } : rows; },
  discover: async () => workerRequest(async () => data(await httpClient.post('/competitors/discovery'))),
  catalog: async (id,params,signal) => workerRequest(async () => data(await httpClient.get(`/competitors/${id}/catalog`,{params,signal}))),
  productCandidates: async (id,productId,signal) => workerRequest(async () => data(await httpClient.get(`/competitors/${id}/products/${productId}/candidates`,{signal}))),
  linkProduct: async (id,payload) => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/product-links`,payload))),
  rejectCandidate: async (id,candidateId) => workerRequest(async () => data(await httpClient.patch(`/competitors/${id}/candidates/${candidateId}`,{rejected:true}))),
  previewProduct: async (id,mappingId) => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/mappings/${mappingId}/preview`,{}, {timeout:30000}))),
  profile: async (_companyId, id) => data(await httpClient.get(`/competitors/${id}`)),
  create: async (_companyId, payload) => workerRequest(async () => data(await httpClient.post('/competitors', payload))),
  update: async (id, alias) => data(await httpClient.patch(`/competitors/${id}`, { alias })),
  track: async (id, isTracked) => workerRequest(async () => data(await httpClient.patch(`/competitors/${id}/tracking`, { isTracked }))),
  schedule: async id => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/monitoring`))),
  cancelDiscovery: async (id,eventId) => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/discovery/${eventId}/cancel`))),
  retryCollection: async (id,sourceId,failedEventId) => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/sources/${sourceId}/collections/retry`,{failedEventId}))),
  reviewSource: async (id, sourceId, payload) => workerRequest(async () => data(await httpClient.post(`/competitors/${id}/sources/${sourceId}/review`, payload, {timeout:35000}))),
  confirm: async (id, mappingId, comparisonConfirmed) => workerRequest(async () => data(await httpClient.patch(`/competitors/${id}/mappings/${mappingId}`, { comparisonConfirmed })))
};
