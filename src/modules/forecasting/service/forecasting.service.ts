import * as forecastingRepo from "../repo/forecasting.repo.js";

export const getDemandOverview = async (
  tenantId: string,
  periodDays: number,
  productId: string
) => {
  const data = await forecastingRepo.getDemandOverview(
    tenantId,
    periodDays,
    productId
  );
  if (!data) throw new Error("Failed to load demand overview");
  return data;
};

export const getDemandDetail = async (tenantId: string, productId: string) => {
  const data = await forecastingRepo.getDemandDetail(tenantId, productId);
  if (!data) throw new Error("Product forecast details not found");
  return data;
};
