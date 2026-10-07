/**
 * CEOPRO deterministic DEV/TEST seed entrypoint.
 *
 * Production bootstrap belongs in prisma/bootstrap/, not here.
 */
import { prisma } from "../../src/config/database.js";
import {
  assertDevelopmentSeedEnvironment,
  requireSeedPassword
} from "./helpers/environment.js";
import { createDeterministicUuidFactory } from "./helpers/ids.js";
import { createSeedClock } from "./helpers/time.js";
import { section, step, success } from "./helpers/logs.js";
import { seedIdentityAndAccess } from "./seeders/identity.seeder.js";
import { seedBilling } from "./seeders/billing.seeder.js";
import { seedCommerceData } from "./seeders/commerce.seeder.js";
import { seedMarketIntelligence } from "./seeders/market-intelligence.seeder.js";
import { seedForecasting } from "./seeders/forecasting.seeder.js";
import { verifyDevelopmentSeed } from "./seeders/verification.seeder.js";

async function main() {
  assertDevelopmentSeedEnvironment("seed development fixtures");

  const password = requireSeedPassword();
  const uuid = createDeterministicUuidFactory("ceopro-fixture-v1");
  const clock = createSeedClock();

  section("CEOPRO Development/Test Seed");

  step("Seeding tenants, users, roles, sessions, and invitations");
  const identity = await seedIdentityAndAccess({
    uuid,
    password,
    clock
  });
  success("Identity and access fixtures ready");

  step("Seeding demo billing/subscription fixtures");
  await seedBilling({
    tenantIds: identity.tenantIds,
    uuid,
    clock
  });
  success("Billing fixtures ready");

  step("Seeding products, inventory, documents, sales, and reviews");
  const commerce = await seedCommerceData({
    tenantIds: identity.tenantIds,
    users: identity.users,
    uuid,
    clock
  });
  success("Commerce fixtures ready");

  step("Seeding competitors, mappings, prices, and score snapshots");
  const market = await seedMarketIntelligence({
    tenantIds: identity.tenantIds,
    products: commerce.products,
    uuid,
    clock
  });
  success("Market-intelligence fixtures ready");

  step("Seeding demand forecasts and inventory recommendations");
  const forecasting = await seedForecasting({
    products: commerce.products,
    uuid,
    clock
  });
  success("Forecasting fixtures ready");

  step("Verifying seeded fixture visibility");
  await verifyDevelopmentSeed({
    tenantIds: identity.tenantIds,
    users: identity.users,
    products: commerce.products,
    competitors: market.competitors,
    tracked: market.tracked,
    mappings: market.mappings,
    prices: market.prices,
    transactions: commerce.transactions,
    reviews: commerce.reviews,
    forecasts: forecasting.forecasts,
    snapshots: market.snapshots
  });

  success("Development/test seed completed and verified");
}

main()
  .catch((error) => {
    console.error("");
    console.error("Development/test seed failed:");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
