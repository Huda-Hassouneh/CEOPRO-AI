/**
 * Isolated, repeatable DEV/TEST fixtures for Dashboard Growth and
 * Review Sentiment KPIs.
 */
import { prisma } from "../../src/config/database.js";
import {
  assertDashboardArguments,
  assertDevelopmentSeedEnvironment,
  getDashboardPeriodDays,
  requireDashboardTenantId
} from "./helpers/environment.js";
import {
  cleanDashboardMetricsSeed,
  seedDashboardMetrics
} from "./seeders/dashboard-metrics.seeder.js";

async function main() {
  assertDevelopmentSeedEnvironment("seed dashboard metric fixtures");

  const tenantId = requireDashboardTenantId();
  const periodDays = getDashboardPeriodDays();
  const { clean } = assertDashboardArguments(process.argv.slice(2));

  if (clean) {
    await cleanDashboardMetricsSeed(tenantId);
    return;
  }

  await seedDashboardMetrics({ tenantId, periodDays });
}

main()
  .catch((error) => {
    console.error("");
    console.error("Dashboard metric seed failed:");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
