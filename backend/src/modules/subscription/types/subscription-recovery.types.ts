export const RECOVERABLE_SUBSCRIPTION_STATUSES = [
  "pending",
  "past_due",
  "payment_failed",
  "paused"
] as const;

export type RecoverableSubscriptionStatus =
  (typeof RECOVERABLE_SUBSCRIPTION_STATUSES)[number];

export type SubscriptionRecoveryType =
  | "complete_payment"
  | "resolve_payment"
  | "manage_billing";

export type SubscriptionRecoveryData = {
  type: SubscriptionRecoveryType;
  url: string;
};

export function isRecoverableSubscriptionStatus(
  status: string
): status is RecoverableSubscriptionStatus {
  return RECOVERABLE_SUBSCRIPTION_STATUSES.some(
    (recoverableStatus) => recoverableStatus === status
  );
}
