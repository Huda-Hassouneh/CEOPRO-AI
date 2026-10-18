const ACCESS_GRANTED_STATUSES = new Set(["active", "trialing"]);
const PAYMENT_ISSUE_STATUSES = new Set(["past_due", "payment_failed"]);
const TERMINAL_STATUSES = new Set(["cancelled", "canceled", "expired"]);
const RECOVERABLE_STATUSES = new Set([
  "pending",
  "past_due",
  "payment_failed",
  "paused"
]);

export const normalizeSubscriptionStatus = (status) =>
  typeof status === "string" ? status.trim().toLowerCase() : "";

export const isAccessGrantingSubscriptionStatus = (status) =>
  ACCESS_GRANTED_STATUSES.has(normalizeSubscriptionStatus(status));

export const isRecoverableSubscriptionStatus = (status) =>
  RECOVERABLE_STATUSES.has(normalizeSubscriptionStatus(status));

export const getSubscriptionResultStatus = (status) => {
  const normalizedStatus = normalizeSubscriptionStatus(status);

  if (ACCESS_GRANTED_STATUSES.has(normalizedStatus)) {
    return "confirmed";
  }

  if (normalizedStatus === "pending") {
    return "pending";
  }

  if (PAYMENT_ISSUE_STATUSES.has(normalizedStatus)) {
    return "payment_issue";
  }

  if (normalizedStatus === "paused") {
    return "paused";
  }

  if (TERMINAL_STATUSES.has(normalizedStatus)) {
    return "failed";
  }

  return "error";
};

export const getSubscriptionRecoveryCopyKey = (status) => {
  const normalizedStatus = normalizeSubscriptionStatus(status);

  if (normalizedStatus === "pending") {
    return "pending";
  }

  if (PAYMENT_ISSUE_STATUSES.has(normalizedStatus)) {
    return "paymentIssue";
  }

  if (normalizedStatus === "paused") {
    return "paused";
  }

  return null;
};
