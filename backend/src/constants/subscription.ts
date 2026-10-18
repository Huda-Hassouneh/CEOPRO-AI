export const CURRENT_SUBSCRIPTION_STATUSES = [
  "trialing",
  "active",
  "past_due",
  "pending",
  "payment_failed",
  "paused"
] as const;

export const ACCESS_GRANTING_STATUSES = ["active", "trialing"] as const;

export type AccessGrantingSubscriptionStatus =
  (typeof ACCESS_GRANTING_STATUSES)[number];

export function grantsSubscriptionAccess(status: string): boolean {
  return ACCESS_GRANTING_STATUSES.some(
    (accessStatus) => accessStatus === status
  );
}
