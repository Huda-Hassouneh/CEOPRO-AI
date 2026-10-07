import type { PlanPriceVersion } from "../../../generated/prisma/client.js";
import subscriptionRepo from "../repo/subscription.repo.js";

type CurrentSubscriptionRecord = NonNullable<
  Awaited<ReturnType<typeof subscriptionRepo.getCurrentSubscriptionByTenant>>
>;

export type CurrentSubscriptionPrice = Pick<
  PlanPriceVersion,
  "amount" | "currency" | "intervalUnit" | "intervalCount"
> & {
  period: PlanPriceVersion["periodCode"];
};

export type CurrentSubscriptionResponse = CurrentSubscriptionRecord & {
  currentPrice: CurrentSubscriptionPrice | null;
};
