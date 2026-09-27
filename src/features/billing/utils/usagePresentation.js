// The API sends boolean entitlements with a null limit and zero usage.
// Treating them as numeric quotas incorrectly displays "0 / Unlimited".
export function getUsagePresentation(feature, used, limit) {
  if (feature?.type === "boolean") return { kind: "included" };
  if (feature?.type !== "limit") return { kind: "unavailable" };
  if (typeof used !== "number" || !Number.isFinite(used) || used < 0)
    return { kind: "unavailable" };
  if (limit === null) return { kind: "unlimited", used };
  if (typeof limit !== "number" || !Number.isFinite(limit) || limit < 0)
    return { kind: "unavailable" };
  return { kind: "limited", used, limit };
}
