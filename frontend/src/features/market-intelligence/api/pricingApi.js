import { translateCurrent } from '../../../shared/lib/i18n.js';
import httpClient from "../../../shared/lib/httpClient.js";

export const pricingApi = {
  history: async (productId,signal) => {
    const response=await httpClient.get('/features/pricing/history',{params:{product_id:productId},signal});
    return response.data?.data??response.data;
  },
  generateRecommendation: async (productId,requestId) => {
    if (!productId || productId === "all") {
      throw new Error(translateCurrent("interfaceCopy.productRequired"));
    }

    const response = await httpClient.post(
      "/features/pricing/recommend",
      {},
      {
        params: {
          product_id: productId,
          request_id: requestId
        }
      }
    );

    return response.data?.data ?? response.data;
  }
};
