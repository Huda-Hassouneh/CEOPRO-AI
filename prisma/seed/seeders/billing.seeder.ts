import { prisma } from "../../../src/config/database.js";
import type { SeedClock } from "../helpers/time.js";

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
    data: subscriptions,
    skipDuplicates: true
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
