export type PlanTransitionType = "upgrade" | "downgrade" | "mixed" | "equivalent";
export type PlanTransitionTiming = "immediate" | "period_end";
export type FeatureChangeDirection = "gain" | "loss" | "unchanged";

export type EntitlementValue = number | null | "absent";

export type PlanFeatureLike = {
  feature_id?: string;
  featureId?: string;
  limit_value?: number | null;
  limitValue?: number | null;
  feature?: {
    id?: string;
    code?: string;
    name?: string;
  } | null;
};

export type PlanWithFeaturesLike = {
  id: string;
  name?: string | null;
  planType?: string | null;
  planFeatures?: PlanFeatureLike[] | null;
};

export type FeatureTransition = {
  featureId: string;
  code: string | null;
  name: string | null;
  from: EntitlementValue;
  to: EntitlementValue;
  direction: FeatureChangeDirection;
};

export type PlanTransitionAnalysis = {
  comparable: boolean;
  type: PlanTransitionType;
  gains: FeatureTransition[];
  losses: FeatureTransition[];
  unchanged: FeatureTransition[];
  hasEntitlementGain: boolean;
  hasEntitlementLoss: boolean;
  recommendedEffectiveTiming: PlanTransitionTiming;
};

type NormalizedEntitlement = {
  featureId: string;
  code: string | null;
  name: string | null;
  limitValue: number | null;
};

function normalizeFeature(link: PlanFeatureLike): NormalizedEntitlement | null {
  const featureId = link.feature_id ?? link.featureId ?? link.feature?.id;
  if (!featureId) return null;

  return {
    featureId,
    code: link.feature?.code ?? null,
    name: link.feature?.name ?? null,
    limitValue:
      link.limit_value !== undefined
        ? link.limit_value
        : link.limitValue !== undefined
          ? link.limitValue
          : null
  };
}

function compareEntitlement(
  current: NormalizedEntitlement | undefined,
  target: NormalizedEntitlement | undefined
): FeatureChangeDirection {
  if (!current && target) return "gain";
  if (current && !target) return "loss";
  if (!current || !target) return "unchanged";

  const from = current.limitValue;
  const to = target.limitValue;

  // null means unlimited (or enabled for boolean features) in the existing plan_features model.
  if (from === null && to === null) return "unchanged";
  if (from === null && to !== null) return "loss";
  if (from !== null && to === null) return "gain";

  if ((to as number) > (from as number)) return "gain";
  if ((to as number) < (from as number)) return "loss";
  return "unchanged";
}

/**
 * Compare product entitlements independently from price.
 *
 * Important domain rule:
 * - Any entitlement loss means the target should not replace already-paid
 *   access immediately; it should take effect at period end.
 * - A transition with gains only may take effect immediately.
 * - If neither plan has configured plan_features, comparable=false so callers
 *   can preserve legacy tier/commercial fallback behavior.
 */
export function analyzePlanTransition(
  currentPlan: PlanWithFeaturesLike,
  targetPlan: PlanWithFeaturesLike
): PlanTransitionAnalysis {
  const currentFeatures = (currentPlan.planFeatures ?? [])
    .map(normalizeFeature)
    .filter((item): item is NormalizedEntitlement => Boolean(item));
  const targetFeatures = (targetPlan.planFeatures ?? [])
    .map(normalizeFeature)
    .filter((item): item is NormalizedEntitlement => Boolean(item));

  const comparable = currentFeatures.length > 0 || targetFeatures.length > 0;

  if (!comparable) {
    return {
      comparable: false,
      type: "equivalent",
      gains: [],
      losses: [],
      unchanged: [],
      hasEntitlementGain: false,
      hasEntitlementLoss: false,
      recommendedEffectiveTiming: "immediate"
    };
  }

  const currentById = new Map(currentFeatures.map((item) => [item.featureId, item]));
  const targetById = new Map(targetFeatures.map((item) => [item.featureId, item]));
  const featureIds = new Set([...currentById.keys(), ...targetById.keys()]);

  const changes: FeatureTransition[] = [];

  for (const featureId of featureIds) {
    const current = currentById.get(featureId);
    const target = targetById.get(featureId);
    const direction = compareEntitlement(current, target);
    const representative = target ?? current!;

    changes.push({
      featureId,
      code: representative.code,
      name: representative.name,
      from: current ? current.limitValue : "absent",
      to: target ? target.limitValue : "absent",
      direction
    });
  }

  const gains = changes.filter((change) => change.direction === "gain");
  const losses = changes.filter((change) => change.direction === "loss");
  const unchanged = changes.filter((change) => change.direction === "unchanged");

  let type: PlanTransitionType = "equivalent";
  if (gains.length > 0 && losses.length > 0) type = "mixed";
  else if (gains.length > 0) type = "upgrade";
  else if (losses.length > 0) type = "downgrade";

  return {
    comparable: true,
    type,
    gains,
    losses,
    unchanged,
    hasEntitlementGain: gains.length > 0,
    hasEntitlementLoss: losses.length > 0,
    recommendedEffectiveTiming: losses.length > 0 ? "period_end" : "immediate"
  };
}
