import * as dashboardRepo from "../repo/dashboard.repo.js";

export const getDashboardAggregate = async (
  tenantId: string,
  userId: string,
  periodDays: number
) => {
  const dashboardData = await dashboardRepo.getMainDashboardKPIs(
    tenantId,
    userId,
    periodDays
  );

  if (!dashboardData) {
    throw new Error("Failed to generate dashboard metrics");
  }

  return dashboardData;
};
