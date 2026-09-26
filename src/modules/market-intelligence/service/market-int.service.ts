import * as marketIntelligenceRepo from "../repo/market-int.repo.js";

export const getMarketIntelligence = async (
  tenantId: string,
  productId?: string,
  periodDays?: number
) => {
  const data = await marketIntelligenceRepo.getMarketIntelligence(
    tenantId,
    productId,
    periodDays
  );
  console.log({ data: data?.competitors });
  if (!data) throw new Error("Failed to load market intelligence data");
  return data;
};
