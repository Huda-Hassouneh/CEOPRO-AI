import { configKeys } from "../../../config/keys.config.js";
import type { CustomPlanPricingPolicyUpdateInput } from "../../../DTO/customPlan.dto.js";
import { getAppConfig, upsertAppConfig } from "../repo/repo.js";

export type AutomaticFeatureLimit = {
  min?: number;
  max?: number;
  step?: number;
};

export type CustomPlanPricingPolicy = {
  currency: string;
  targetGrossMargin: number;
  fixedPlatformFee: number;
  monthlyInfrastructureCost: number;
  activePayingTenants: number;
  estimatedOtherCost: number;
  roundingIncrement: number;
  maxAutomaticMonthlyPrice: number;
  maxAutomaticQuotaPerFeature: number;
  enforceVendorCostRatioFloor: boolean;
  maxVendorCostRevenueRatio: number;
  fxRate: number | null;
  fxSourceCurrency: string | null;
  fxTargetCurrency: string | null;
  fxSource: string | null;
  fxRateAt: string | null;
  trialPeriodValue: number;
  billingOptions: Array<{
    period: string;
    months: number;
    discountPercent: number;
  }>;
  featureLimits: Record<string, AutomaticFeatureLimit>;
};

export const DEFAULT_CUSTOM_PLAN_PRICING_POLICY: CustomPlanPricingPolicy = {
  currency: "JOD",

  targetGrossMargin: 0.35,
  fixedPlatformFee: 25,

  monthlyInfrastructureCost: 0,
  activePayingTenants: 1,
  estimatedOtherCost: 0,

  roundingIncrement: 1,

  maxAutomaticMonthlyPrice: 2500,
  maxAutomaticQuotaPerFeature: 500000,

  enforceVendorCostRatioFloor: false,
  maxVendorCostRevenueRatio: 0.2,

  // USD -> JOD conversion used for USD vendor rates
  fxRate: 0.709,
  fxSourceCurrency: "USD",
  fxTargetCurrency: "JOD",
  fxSource: "Configured USD/JOD pricing rate",
  fxRateAt: new Date().toISOString(),

  trialPeriodValue: 0,

  billingOptions: [
    {
      period: "monthly",
      months: 1,
      discountPercent: 0,
    },
    {
      period: "three-months",
      months: 3,
      discountPercent: 10,
    },
    {
      period: "six-months",
      months: 6,
      discountPercent: 20,
    },
  ],

  featureLimits: {},
};

function asFiniteNumber(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function sanitizePolicy(raw: unknown): CustomPlanPricingPolicy {
  const source =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, any>)
      : {};
  const defaults = DEFAULT_CUSTOM_PLAN_PRICING_POLICY;

  const billingOptions =
    Array.isArray(source.billingOptions) && source.billingOptions.length
      ? source.billingOptions
          .filter((item: any) => item && typeof item === "object")
          .map((item: any) => ({
            period: String(item.period ?? "").trim(),
            months: Math.max(1, Math.trunc(asFiniteNumber(item.months, 1))),
            discountPercent: Math.min(
              100,
              Math.max(0, asFiniteNumber(item.discountPercent, 0)),
            ),
          }))
          .filter((item: any) => item.period)
      : defaults.billingOptions;

  const rawFeatureLimits =
    source.featureLimits &&
    typeof source.featureLimits === "object" &&
    !Array.isArray(source.featureLimits)
      ? (source.featureLimits as Record<string, any>)
      : {};
  const featureLimits: Record<string, AutomaticFeatureLimit> = {};
  for (const [code, rawLimit] of Object.entries(rawFeatureLimits)) {
    if (
      !code ||
      !rawLimit ||
      typeof rawLimit !== "object" ||
      Array.isArray(rawLimit)
    )
      continue;
    const min =
      rawLimit.min == null
        ? undefined
        : Math.max(0, Math.trunc(asFiniteNumber(rawLimit.min, 0)));
    const rawMax =
      rawLimit.max == null
        ? undefined
        : Math.max(1, Math.trunc(asFiniteNumber(rawLimit.max, 1)));
    const max = rawMax == null ? undefined : Math.max(min ?? 0, rawMax);
    const step =
      rawLimit.step == null
        ? undefined
        : Math.max(1, Math.trunc(asFiniteNumber(rawLimit.step, 1)));
    featureLimits[code] = {
      ...(min != null ? { min } : {}),
      ...(max != null ? { max } : {}),
      ...(step != null ? { step } : {}),
    };
  }

  return {
    currency: /^[A-Z]{3}$/.test(String(source.currency ?? "").toUpperCase())
      ? String(source.currency).toUpperCase()
      : defaults.currency,
    targetGrossMargin: Math.min(
      0.999999,
      Math.max(
        0,
        asFiniteNumber(source.targetGrossMargin, defaults.targetGrossMargin),
      ),
    ),
    fixedPlatformFee: Math.max(
      0,
      asFiniteNumber(source.fixedPlatformFee, defaults.fixedPlatformFee),
    ),
    monthlyInfrastructureCost: Math.max(
      0,
      asFiniteNumber(
        source.monthlyInfrastructureCost,
        defaults.monthlyInfrastructureCost,
      ),
    ),
    activePayingTenants: Math.max(
      1,
      Math.trunc(
        asFiniteNumber(
          source.activePayingTenants,
          defaults.activePayingTenants,
        ),
      ),
    ),
    estimatedOtherCost: Math.max(
      0,
      asFiniteNumber(source.estimatedOtherCost, defaults.estimatedOtherCost),
    ),
    roundingIncrement: Math.max(
      0,
      asFiniteNumber(source.roundingIncrement, defaults.roundingIncrement),
    ),
    maxAutomaticMonthlyPrice: Math.max(
      0.01,
      asFiniteNumber(
        source.maxAutomaticMonthlyPrice,
        defaults.maxAutomaticMonthlyPrice,
      ),
    ),
    maxAutomaticQuotaPerFeature: Math.max(
      1,
      Math.trunc(
        asFiniteNumber(
          source.maxAutomaticQuotaPerFeature,
          defaults.maxAutomaticQuotaPerFeature,
        ),
      ),
    ),
    enforceVendorCostRatioFloor: source.enforceVendorCostRatioFloor === true,
    maxVendorCostRevenueRatio: Math.min(
      1,
      Math.max(
        0.000001,
        asFiniteNumber(
          source.maxVendorCostRevenueRatio,
          defaults.maxVendorCostRevenueRatio,
        ),
      ),
    ),
    fxRate:
      source.fxRate == null
        ? null
        : Math.max(0.00000001, asFiniteNumber(source.fxRate, 1)),
    fxSourceCurrency: /^[A-Z]{3}$/.test(
      String(source.fxSourceCurrency ?? "").toUpperCase(),
    )
      ? String(source.fxSourceCurrency).toUpperCase()
      : null,
    fxTargetCurrency: /^[A-Z]{3}$/.test(
      String(source.fxTargetCurrency ?? "").toUpperCase(),
    )
      ? String(source.fxTargetCurrency).toUpperCase()
      : null,
    fxSource: source.fxSource == null ? null : String(source.fxSource),
    fxRateAt: source.fxRateAt == null ? null : String(source.fxRateAt),
    trialPeriodValue: Math.max(
      0,
      Math.trunc(
        asFiniteNumber(source.trialPeriodValue, defaults.trialPeriodValue),
      ),
    ),
    billingOptions: billingOptions.length
      ? billingOptions
      : defaults.billingOptions,
    featureLimits,
  };
}

export async function getCustomPlanPricingPolicy(): Promise<CustomPlanPricingPolicy> {
  const record = await getAppConfig(configKeys.customPlanPricingPolicyKey);
  if (!record?.value) return DEFAULT_CUSTOM_PLAN_PRICING_POLICY;

  try {
    return sanitizePolicy(JSON.parse(record.value));
  } catch {
    return DEFAULT_CUSTOM_PLAN_PRICING_POLICY;
  }
}

export async function updateCustomPlanPricingPolicy(
  patch: CustomPlanPricingPolicyUpdateInput,
): Promise<CustomPlanPricingPolicy> {
  const current = await getCustomPlanPricingPolicy();
  const next = sanitizePolicy({
    ...current,
    ...patch,
    featureLimits: patch.featureLimits ?? current.featureLimits,
    billingOptions: patch.billingOptions ?? current.billingOptions,
  });

  await upsertAppConfig(
    configKeys.customPlanPricingPolicyKey,
    JSON.stringify(next),
  );
  return next;
}

export function resolveAutomaticFeatureLimit(
  featureCode: string,
  policy: CustomPlanPricingPolicy,
): Required<AutomaticFeatureLimit> {
  const configured = policy.featureLimits[featureCode] ?? {};
  const min = Math.max(0, Math.trunc(configured.min ?? 0));
  const max = Math.max(
    min,
    Math.trunc(configured.max ?? policy.maxAutomaticQuotaPerFeature),
  );
  const step = Math.max(1, Math.trunc(configured.step ?? 1));
  return { min, max, step };
}
