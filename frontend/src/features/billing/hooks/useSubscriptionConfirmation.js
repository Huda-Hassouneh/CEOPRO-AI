import {useQuery} from '@tanstack/react-query';
import {useSearchParams} from 'react-router-dom';
import {useAuthStore} from '../../auth/store/authStore.js';
import {billingApi} from '../api/billingApi.js';
import httpClient from '../../../shared/lib/httpClient.js';
// A redirect, local trial, or old active subscription cannot confirm this Checkout.
export function useSubscriptionConfirmation(){
 const [params]=useSearchParams(),id=params.get('session_id'),tenant=useAuthStore(s=>s.tenantId);
 const subscription=useQuery({queryKey:['subscription',tenant],queryFn:billingApi.getSubscription});
 const query=useQuery({queryKey:['onboarding-checkout-confirmation',tenant,id],enabled:Boolean(id),retry:false,
  queryFn:async()=>(await httpClient.get('/billing/checkout-status',{params:{session_id:id}})).data,
  refetchInterval:q=>q.state.data?.state==='confirmed'||q.state.dataUpdateCount>=20?false:3000});
 const status=query.isError?'error':query.data?.state==='confirmed'?'confirmed':'pending';
 return {status,subscription:subscription.data,isChecking:query.isFetching,retry:()=>{subscription.refetch();query.refetch();}};
}
