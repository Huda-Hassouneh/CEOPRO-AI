const reasons = new Set([
  "MISSING_INVENTORY", "DUPLICATE_WAREHOUSE", "INVALID_STOCK_DATE", "STALE_INVENTORY", "INVALID_INVENTORY", "UNDATED_INVENTORY",
  "INCOMPLETE_FORECAST", "NO_HORIZON_RECOMMENDATION", "NO_STORED_RECOMMENDATION", "INVALID_RECOMMENDATION", "OUTDATED_RECOMMENDATION",
  "STOCK_CHANGED", "MISSING_SAFETY_STOCK", "INCONSISTENT_RECOMMENDATION"
]);
export function inventoryReason(status, t) {
  return t(reasons.has(status?.reason) ? `demandApproved.inventoryEvidence.reasons.${status.reason}` : "demandApproved.empty.recommendationDescription");
}
