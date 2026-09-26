import * as competitorsRepo from "./repo.js";

export const getCompetitorsList = async (tenantId: string) => {
  return await competitorsRepo.getCompetitorsList(tenantId);
};

export const getCompetitorProfile = async (
  tenantId: string,
  competitorId: string
) => {
  const profile = await competitorsRepo.getCompetitorProfile(
    tenantId,
    competitorId
  );
  if (!profile)
    throw new Error("Competitor not found or not tracked by this tenant");
  return profile;
};

export const createCompetitor = async (tenantId: string, payload: any) => {
  if (!payload.name) throw new Error("Competitor name is required");
  return await competitorsRepo.createCompetitor(tenantId, payload);
};
