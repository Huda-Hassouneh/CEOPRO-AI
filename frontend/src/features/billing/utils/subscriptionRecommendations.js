import { getUsagePresentation } from "./usagePresentation.js";

const CONTEXT_LIMIT_KEYS = Object.freeze({
  "data-credits": "dataCredits",
  "ai-credits": "aiCredits",
  "product-limit": "tracked_products",
  "competitor-limit": "tracked_competitors",
  "rag-limit": "rag_assistant",
  "storage-limit": "document_storage_mb"
});

export function getUsageState(used, limit) {
  if (!Number.isFinite(used)) return "unknown";

  // null means unlimited for limit-type entitlements.
  if (limit === null) return "unlimited";

  if (!Number.isFinite(limit) || limit < 0) return "unknown";

  if (limit === 0) return "notIncluded";
  if (used >= limit) return "reached";

  if (limit > 0 && used / limit >= 0.8) {
    return "approaching";
  }

  return "normal";
}

export function getUpgradeRecommendation(subscription, reason) {
  if (!subscription) return null;
  if (subscription.planId === "custom") return null;
  if (["trialing", "trial"].includes(subscription.status)) return { type: "trial" };

  const supportedReasonKey = CONTEXT_LIMIT_KEYS[reason];
  if (
    supportedReasonKey &&
    getUsagePresentation(
      subscription.features?.[supportedReasonKey] || { type: "limit" },
      subscription.usage?.[supportedReasonKey],
      subscription.limits?.[supportedReasonKey]
    ).kind === "limited" &&
    getUsageState(
      subscription.usage?.[supportedReasonKey],
      subscription.limits?.[supportedReasonKey]
    ) === "reached"
  ) {
    return { type: "reached", key: supportedReasonKey, contextual: true };
  }

  const keys = Object.keys(subscription.limits || {}).filter(
    (key) =>
      getUsagePresentation(
        subscription.features?.[key] || { type: "limit" },
        subscription.usage?.[key],
        subscription.limits?.[key]
      ).kind === "limited"
  );
  const reached = keys.find(
    (key) =>
      getUsageState(subscription.usage[key], subscription.limits[key]) ===
      "reached"
  );
  if (reached) return { type: "reached", key: reached };
  const approaching = keys.find(
    (key) =>
      getUsageState(subscription.usage[key], subscription.limits[key]) ===
      "approaching"
  );
  return approaching ? { type: "approaching", key: approaching } : null;
}
