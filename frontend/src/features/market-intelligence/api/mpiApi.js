import httpClient from '../../../shared/lib/httpClient.js';

export const mpiApi = {
  history:async({subjectType,subjectId,limit=20,offset=0})=>(await httpClient.get('/mpi/history',{params:{subject_type:subjectType,...(subjectId?{subject_id:subjectId}:{}),limit,offset}})).data,
  summary: async ({ subjectType, subjectId }) => {
    const response = await httpClient.get('/mpi/summary', {
      params: { subject_type: subjectType, ...(subjectId ? { subject_id: subjectId } : {}) },
    });
    return response.data;
  },
};
