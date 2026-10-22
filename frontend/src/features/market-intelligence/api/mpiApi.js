import httpClient from '../../../shared/lib/httpClient.js';

export const mpiApi = {
  summary: async ({ subjectType, subjectId }) => {
    const response = await httpClient.get('/mpi/summary', {
      params: { subject_type: subjectType, ...(subjectId ? { subject_id: subjectId } : {}) },
    });
    return response.data;
  },
};
