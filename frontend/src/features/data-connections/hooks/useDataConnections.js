import { useQuery } from "@tanstack/react-query";
import { dataConnectionsApi } from "../api/dataConnectionsApi.js";

export function useDataConnections(companyId) {
  return useQuery({
    queryKey: ["data-connection", companyId],
    queryFn: () => dataConnectionsApi.list({ companyId }),
    refetchInterval: query => {
      const stores=query.state.data?.connectedSources?.filter(source=>source.provider==='woocommerce')||[];
      return stores.some(source=>source.status==='processing')?5000:stores.length?60000:false;
    }
  });
}
