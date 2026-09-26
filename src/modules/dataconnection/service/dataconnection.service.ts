import { dataManagementRepo } from "../repo/dataconnection.repo.js";

export const getDataConnectionsOverview = async (tenantId: string) => {
  const data = await dataManagementRepo.getDataConnectionsOverview(tenantId);
  if (!data) throw new Error("Failed to load data connections overview");
  return data;
};
