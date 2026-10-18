import { useMutation,useQuery,useQueryClient } from "@tanstack/react-query";
import {useSWRConfig} from 'swr';
import {useAuthStore} from '../../auth/store/authStore.js';
import { pricingApi } from "../api/pricingApi.js";

export function usePricingRecommendation() {
  const client=useQueryClient();const {mutate}=useSWRConfig();
  return useMutation({
    mutationFn: ({productId,requestId}) => pricingApi.generateRecommendation(productId,requestId),
    retry:false,
    onSuccess:(recommendation,variables)=>{
      const auth=useAuthStore.getState();
      if(auth.tenantId!==variables.tenantId||(auth.user?.user_id??auth.user?.id)!==variables.userId)return;
      client.setQueryData(['pricing-history',variables.tenantId,variables.userId,variables.productId],current=>({
        recommendations:[recommendation,...(current?.recommendations??[]).filter(r=>r.request_id!==recommendation.request_id)].slice(0,20)
      }));
    },
    onSettled:async()=>{
      await Promise.all([client.invalidateQueries({queryKey:['pricing-history']}),
        client.invalidateQueries({queryKey:['subscription','usage']}),mutate('subscription-current-usage')]);
    }
  });
}

export function usePricingHistory(productId,enabled){
  const tenantId=useAuthStore(s=>s.tenantId),userId=useAuthStore(s=>s.user?.user_id??s.user?.id);
  return useQuery({queryKey:['pricing-history',tenantId,userId,productId],
    queryFn:({signal})=>pricingApi.history(productId,signal),enabled:Boolean(enabled&&tenantId&&userId&&productId),
    retry:false,staleTime:0});
}
