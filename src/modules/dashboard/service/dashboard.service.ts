import * as dashboardRepo from "../repo/dashboard.repo.js";

export const getDashboardAggregate = async (
  tenantId: string,
  periodDays: number
) => {
  // Add any business validation or external API aggregations here in the future

  const dashboardData = await dashboardRepo.getMainDashboardKPIs(
    tenantId,
    periodDays
  );

  if (!dashboardData) {
    throw new Error("Failed to generate dashboard metrics");
  }

  return dashboardData;
};
