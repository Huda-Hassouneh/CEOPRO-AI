export type EntitlementDecisionInput = {
  included: boolean;
  isUnlimited: boolean;
  isExceeded: boolean;
  aggregationType: string | null;
};

export type EntitlementBlockReason =
  | "FEATURE_NOT_INCLUDED"
  | "QUOTA_EXHAUSTED"
  | "CAPACITY_REACHED";

export function getConsumptionBlockReason(
  input: EntitlementDecisionInput
): EntitlementBlockReason | null {
  if (!input.included) return "FEATURE_NOT_INCLUDED";
  if (input.isUnlimited || !input.isExceeded) return null;
  return input.aggregationType === "max"
    ? "CAPACITY_REACHED"
    : "QUOTA_EXHAUSTED";
}


export function hasRemainingCapacity(input: {
  currentUsage: number;
  limit: number | null;
  additionalAmount?: number;
}): boolean {
  const additionalAmount = input.additionalAmount ?? 1;
  if (!Number.isFinite(input.currentUsage) || input.currentUsage < 0) {
    throw new Error("currentUsage must be a non-negative number.");
  }
  if (!Number.isFinite(additionalAmount) || additionalAmount <= 0) {
    throw new Error("additionalAmount must be a positive number.");
  }
  if (input.limit === null) return true;
  return input.currentUsage + additionalAmount <= input.limit;
}
