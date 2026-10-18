import { prisma } from "../../../src/config/database.js";
import type { SeedClock } from "../helpers/time.js";
import { CANONICAL_FEATURES } from "../../../src/modules/features/types/feature.catalog.js";

/** A dev-only plan must enable the new database-enforced capacity guards. */
const DEMO_CAPACITY_LIMITS: Readonly<Record<string, number | null>> = {
  product_management: null,
  tracked_products: 100,
  competitor_management: null,
  tracked_competitors: 50
};

async function ensureDemoCapacityEntitlements(planId: string) {
  for (const code of Object.keys(DEMO_CAPACITY_LIMITS)) {
    const definition = CANONICAL_FEATURES.find((item) => item.code === code);
    if (!definition) {
      throw new Error(`Missing canonical feature definition: ${code}`);
    }
    // Do not run the destructive production feature bootstrap for fixture data.
    const feature = await prisma.feature.upsert({
      where: { code },
      update: {},
      create: { ...definition }
    });
    await prisma.planFeature.upsert({
      where: {
        plan_id_feature_id: {
          plan_id: planId,
          feature_id: feature.id
        }
      },
      update: { limit_value: DEMO_CAPACITY_LIMITS[code] },
      create: {
        plan_id: planId,
        feature_id: feature.id,
        limit_value: DEMO_CAPACITY_LIMITS[code]
      }
    });
  }
}

/** Keep canceled/past-due examples in the final dataset, but allow fixture insertion. */
export async function restoreDemoSubscriptionStatuses(
  subscriptions: ReadonlyArray<{ id: string; planId: string; status: string }>
): Promise<void> {
  for (const subscription of subscriptions) {
    await prisma.subscription.updateMany({
      where: {
        id: subscription.id,
        planId: subscription.planId,
        paymentProvider: "fixture"
      },
      data: { status: subscription.status }
    });
  }
}

export async function seedBilling(args: {
  tenantIds: string[];
  uuid: (key: string) => string;
  clock: SeedClock;
}) {
  const { tenantIds, uuid, clock } = args;
  const planId = uuid("plan:demo");

  await prisma.plan.createMany({
    data: [
      {
        id: planId,
        name: "Development Showcase",
        name_ar: "عرض تجريبي",
        description:
          "Synthetic integration fixture; no external payment provider is connected.",
        price: 49,
        currency: "JOD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month"
      }
    ],
    skipDuplicates: true
  });

  await ensureDemoCapacityEntitlements(planId);

  const subscriptions = tenantIds.map((tenantId, index) => ({
    id: uuid(`subscription:${index}`),
    tenantId,
    planId,
    paymentProvider: "fixture",
    status: ["active", "trialing", "active", "canceled", "active", "past_due"][
      index
    ],
    currentPeriodStart: clock.ago(index === 3 ? 70 : 15),
    currentPeriodEnd: clock.ago(index === 3 ? 40 : index === 0 ? -2 : -15),
    cancelAtPeriodEnd: index === 2,
    cancelledAt: index === 3 ? clock.ago(40) : null
  }));

  await prisma.subscription.createMany({
    // The capacity triggers allow inserts only for active/trialing subscriptions.
    // Restore the final demo statuses in main.ts even if a later seeder fails.
    data: subscriptions.map((subscription) => ({
      ...subscription,
      status: subscription.status === "trialing" ? "trialing" : "active"
    })),
    skipDuplicates: true
  });

  // Rerunning after a partial seed must also activate existing fixture rows.
  await prisma.subscription.updateMany({
    where: {
      id: { in: subscriptions.map((subscription) => subscription.id) },
      planId,
      paymentProvider: "fixture"
    },
    data: { status: "active" }
  });

  await prisma.paymentTransaction.createMany({
    data: subscriptions
      .filter((_, index) => index !== 1)
      .map((subscription, index) => ({
        id: uuid(`payment:${index}`),
        subscriptionId: subscription.id,
        amount: 49,
        currency: "JOD",
        status: index === 4 ? "failed" : "succeeded",
        paidAt: index === 4 ? null : clock.ago(14)
      })),
    skipDuplicates: true
  });

  return { subscriptions };
}
