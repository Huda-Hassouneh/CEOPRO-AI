import test from "node:test";
import assert from "node:assert/strict";
import {
  assertProductionPlanTestEnvironment,
  disconnectProductionPlanDb,
  loadProductionPlans,
} from "./_production-plan-helpers.js";

assertProductionPlanTestEnvironment();

test("27.01 public catalog exposes only active, tenant-neutral standard plans", async () => {
  const { prisma, getPlans } = await loadProductionPlans();
  const marker = `catalog-${Date.now()}`;
  const tenant = await prisma.company.create({
    data: {
      businessName: `Catalog Boundary ${marker}`,
      businessType: "test",
      countryCode: "JO",
      primaryCurrency: "USD",
    },
  });
  const rows: string[] = [];
  try {
    const active = await prisma.plan.create({
      data: {
        name: `Active ${marker}`,
        name_ar: `Active ${marker}`,
        tierLevel: 1,
        planType: "standard",
        tenantId: null,
        price: 10,
        currency: "USD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month",
        billingOptions: [{ period: "monthly", months: 1, discountPercent: 0 }],
        isActive: true,
      },
    });
    rows.push(active.id);
    const inactive = await prisma.plan.create({
      data: {
        name: `Inactive ${marker}`,
        name_ar: `Inactive ${marker}`,
        tierLevel: 2,
        planType: "standard",
        tenantId: null,
        price: 20,
        currency: "USD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month",
        billingOptions: [{ period: "monthly", months: 1, discountPercent: 0 }],
        isActive: false,
      },
    });
    rows.push(inactive.id);
    const custom = await prisma.plan.create({
      data: {
        name: `Private ${marker}`,
        name_ar: `Private ${marker}`,
        tierLevel: null,
        planType: "custom",
        tenantId: tenant.id,
        price: 99,
        currency: "USD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month",
        billingOptions: [{ period: "monthly", months: 1, discountPercent: 0 }],
        isActive: true,
      },
    });
    rows.push(custom.id);

    const catalog = await getPlans();
    const ids = new Set(catalog.map((plan: any) => plan.id));
    assert.equal(ids.has(active.id), true);
    assert.equal(ids.has(inactive.id), false);
    assert.equal(ids.has(custom.id), false);
  } finally {
    await prisma.plan.deleteMany({ where: { id: { in: rows } } });
    await prisma.company.deleteMany({ where: { id: tenant.id } });
    await disconnectProductionPlanDb();
  }
});
