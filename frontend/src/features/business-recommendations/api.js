import httpClient from '../../shared/lib/httpClient.js';
const base='/features/business-recommendations';
const unwrap=r=>r.data?.data??r.data;
export const recommendationsApi={
 list:async(state,page,signal)=>unwrap(await httpClient.get(base,{params:{state,page},signal})),
 refresh:async requestId=>unwrap(await httpClient.post(base+'/refresh',{request_id:requestId})),
 state:async(id,state)=>unwrap(await httpClient.patch(base+'/'+encodeURIComponent(id)+'/state',{state}))
};
