import { createHash } from "node:crypto";
import { Prisma } from "../../../generated/prisma/client.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { ServiceResult } from "../../../types/service.js";
import type {
  CustomPlanInstantCheckoutInput,
  CustomPlanManualReviewInput,
  CustomPlanPreviewInput,
} from "../../../DTO/customPlan.dto.js";
import customPlanRepository from "../repo/custom-plan.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { calculateCustomPlanPrice } from "./custom-plan-pricing.service.js";
import {
  getCustomPlanPricingPolicy,
  resolveAutomaticFeatureLimit,
  type CustomPlanPricingPolicy,
} from "./custom-plan-policy.service.js";
import { acceptCustomPlanQuote } from "./custom-plan.service.js";
import { checkoutService } from "./subscription.service.js";
import { changePlanService } from "./plans.service.js";

const decimal = (value: number | string | Prisma.Decimal) =>
  new Prisma.Decimal(value);

function priceWithDiscount(
  basePrice: number,
  months: number,
  discountPercent: number,
) {
  return Number((basePrice * months * (1 - discountPercent / 100)).toFixed(2));
}

function configurationHash(input: CustomPlanPreviewInput) {
  const normalized = {
    billingPeriod: input.billingPeriod,
    features: [...input.features]
      .map((item) => ({
        featureId: item.featureId,
        limitValue: item.limitValue ?? null,
      }))
      .sort((a, b) => a.featureId.localeCompare(b.featureId)),
  };
  return createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
}

function pricingFingerprint(calculated: any) {
  const normalized = {
    currency: calculated.policy?.currency,
    recommendedPrice:
      calculated.pricing?.recommendedPrice?.toString?.() ??
      String(calculated.pricing?.recommendedPrice),
    billingPeriod: calculated.billingOption?.period,
    discountPercent: calculated.billingOption?.discountPercent,
    vendorRateIds: [
      ...(calculated.vendorRates ?? []).map((rate: any) => rate.id),
    ].sort(),
    vendorBreakdown: calculated.pricing?.vendorBreakdown ?? [],
    targetGrossMargin: calculated.policy?.targetGrossMargin,
    fixedPlatformFee: calculated.policy?.fixedPlatformFee,
    infrastructure: calculated.policy?.monthlyInfrastructureCost,
    activeTenants: calculated.policy?.activePayingTenants,
    otherCost: calculated.policy?.estimatedOtherCost,
    roundingIncrement: calculated.policy?.roundingIncrement,
    fxRate: calculated.policy?.fxRate,
  };
  return createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
}

function mapPricingError(error: unknown): ServiceResult<never> {
  const message =
    error instanceof Error ? error.message : "Custom-plan pricing failed";
  if (message.startsWith("Missing FX rate")) {
    return { success: false, code: ERROR_CODES.FX_RATE_REQUIRED, message };
  }
  if (message.startsWith("Missing vendor rate")) {
    return { success: false, code: ERROR_CODES.VENDOR_RATE_REQUIRED, message };
  }
  return { success: false, code: ERROR_CODES.VALIDATION_ERROR, message };
}

async function calculateConfiguration(input: CustomPlanPreviewInput) {
  const policy = await getCustomPlanPricingPolicy();
  const uniqueIds = [...new Set(input.features.map((item) => item.featureId))];
  if (uniqueIds.length !== input.features.length) {
    return {
      result: {
        success: false as const,
        code: ERROR_CODES.VALIDATION_ERROR,
        message: "Duplicate features are not allowed.",
      },
    };
  }

  const definitions = await customPlanRepository.getFeaturesByIds(uniqueIds);
  if (definitions.length !== uniqueIds.length) {
    return {
      result: {
        success: false as const,
        code: ERROR_CODES.RESOURCE_NOT_FOUND,
        message: "One or more selected features do not exist.",
      },
    };
  }

  const billingOption = policy.billingOptions.find(
    (item) => item.period === input.billingPeriod,
  );
  if (!billingOption) {
    return {
      result: {
        success: false as const,
        code: ERROR_CODES.INVALID_BILLING_PERIOD,
        message: `Billing period '${input.billingPeriod}' is not available for custom plans.`,
      },
    };
  }

  const byId = new Map(definitions.map((feature) => [feature.id, feature]));
  const manualReviewReasons: string[] = [];
  const normalizedFeatures: Array<{
    featureId: string;
    limitValue: number | null;
    estimatedUsage: number;
    feature: (typeof definitions)[number];
  }> = [];

  for (const selected of input.features) {
    const feature = byId.get(selected.featureId)!;
    if (feature.type === "boolean") {
      if (selected.limitValue != null) {
        return {
          result: {
            success: false as const,
            code: ERROR_CODES.INVALID_PARAMETER,
            message: `Boolean feature '${feature.code}' cannot have a numeric limit.`,
          },
        };
      }
      normalizedFeatures.push({
        featureId: feature.id,
        limitValue: null,
        estimatedUsage: 1,
        feature,
      });
      continue;
    }

    if (selected.limitValue == null || !Number.isInteger(selected.limitValue)) {
      return {
        result: {
          success: false as const,
          code: ERROR_CODES.INVALID_PARAMETER,
          message: `Feature '${feature.code}' requires an integer quota.`,
        },
      };
    }

    const limits = resolveAutomaticFeatureLimit(feature.code, policy);
    if (selected.limitValue < limits.min) {
      return {
        result: {
          success: false as const,
          code: ERROR_CODES.INVALID_PARAMETER,
          message: `Feature '${feature.code}' must be at least ${limits.min}.`,
        },
      };
    }
    if ((selected.limitValue - limits.min) % limits.step !== 0) {
      return {
        result: {
          success: false as const,
          code: ERROR_CODES.INVALID_PARAMETER,
          message: `Feature '${feature.code}' must use increments of ${limits.step}.`,
        },
      };
    }
    if (selected.limitValue > limits.max) {
      manualReviewReasons.push(`QUOTA_ABOVE_AUTOMATIC_LIMIT:${feature.code}`);
    }

    normalizedFeatures.push({
      featureId: feature.id,
      limitValue: selected.limitValue,
      estimatedUsage: selected.limitValue,
      feature,
    });
  }

  const vendorRates =
    await customPlanRepository.getActiveVendorRates(uniqueIds);
  const vendorBackedFeatureIds =
    await customPlanRepository.getVendorBackedFeatureIds(uniqueIds);
  const vendorBacked = new Set(vendorBackedFeatureIds);

  // A boolean feature only incurs one vendor unit when the feature is actually
  // backed by a vendor. Non-vendor platform features remain zero vendor cost.
  const pricingFeatures = normalizedFeatures.map((item) => ({
    featureId: item.featureId,
    estimatedUsage:
      item.feature.type === "boolean"
        ? vendorBacked.has(item.featureId)
          ? 1
          : 0
        : item.estimatedUsage,
  }));

  try {
    const pricing = calculateCustomPlanPrice({
      quoteCurrency: policy.currency,
      features: pricingFeatures,
      vendorRates,
      monthlyInfrastructureCost: policy.monthlyInfrastructureCost,
      activePayingTenants: policy.activePayingTenants,
      estimatedOtherCost: policy.estimatedOtherCost,
      targetGrossMargin: policy.targetGrossMargin,
      maxVendorCostRevenueRatio: policy.maxVendorCostRevenueRatio,
      enforceVendorCostRatioFloor: policy.enforceVendorCostRatioFloor,
      fixedPlatformFee: policy.fixedPlatformFee,
      roundingIncrement: policy.roundingIncrement,
      vendorCostRequiredFeatureIds: vendorBackedFeatureIds,
      fxRate: policy.fxRate,
      fxSourceCurrency: policy.fxSourceCurrency,
      fxTargetCurrency: policy.fxTargetCurrency,
    });

    const monthlyPrice = Number(pricing.recommendedPrice);
    if (monthlyPrice > policy.maxAutomaticMonthlyPrice) {
      manualReviewReasons.push("PRICE_ABOVE_AUTOMATIC_LIMIT");
    }
    if (pricing.warnings.length) {
      manualReviewReasons.push("UNVERIFIED_VENDOR_RATE");
    }

    const totalPrice = priceWithDiscount(
      monthlyPrice,
      billingOption.months,
      billingOption.discountPercent,
    );

    return {
      result: { success: true as const },
      policy,
      definitions,
      normalizedFeatures,
      vendorRates,
      vendorBackedFeatureIds,
      pricing,
      billingOption,
      monthlyPrice,
      totalPrice,
      manualReviewReasons: [...new Set(manualReviewReasons)],
    };
  } catch (error) {
    return { result: mapPricingError(error) };
  }
}

export async function getCustomPlanConfigurator(): Promise<ServiceResult<any>> {
  const [policy, features] = await Promise.all([
    getCustomPlanPricingPolicy(),
    customPlanRepository.listConfigurableFeatures(),
  ]);

  return {
    success: true,
    data: {
      currency: policy.currency,
      billingOptions: policy.billingOptions,
      trialPeriodValue: policy.trialPeriodValue,
      features: features.map((feature) => {
        const limits =
          feature.type === "limit"
            ? resolveAutomaticFeatureLimit(feature.code, policy)
            : null;
        return {
          id: feature.id,
          code: feature.code,
          name: feature.name,
          name_ar: feature.name_ar,
          description: feature.description,
          description_ar: feature.description_ar,
          type: feature.type,
          unit: feature.unit,
          unit_ar: feature.unit_ar,
          min: limits?.min ?? null,
          max: limits?.max ?? null,
          step: limits?.step ?? null,
        };
      }),
    },
  };
}

export async function previewCustomPlanConfiguration(
  input: CustomPlanPreviewInput,
): Promise<ServiceResult<any>> {
  const calculated = await calculateConfiguration(input);
  if (!calculated.result.success) return calculated.result;

  return {
    success: true,
    data: {
      currency: calculated.policy!.currency,
      billingPeriod: calculated.billingOption!.period,
      months: calculated.billingOption!.months,
      discountPercent: calculated.billingOption!.discountPercent,
      trialPeriodValue: calculated.policy!.trialPeriodValue,
      monthlyPrice: calculated.monthlyPrice,
      price: calculated.totalPrice,
      eligibleForInstantCheckout: calculated.manualReviewReasons!.length === 0,
      manualReviewReasons: calculated.manualReviewReasons,
      features: calculated.normalizedFeatures!.map((item) => ({
        featureId: item.featureId,
        code: item.feature.code,
        name: item.feature.name,
        name_ar: item.feature.name_ar,
        type: item.feature.type,
        unit: item.feature.unit,
        unit_ar: item.feature.unit_ar,
        limitValue: item.limitValue,
      })),
    },
  };
}

async function createOrReuseAutomaticQuote(args: {
  tenantId: string;
  userId: string;
  requestId: string;
  input: CustomPlanPreviewInput;
  calculated: any;
}) {
  const existing = await customPlanRepository.findQuoteForTenant(
    args.requestId,
    args.tenantId,
  );
  const hash = configurationHash(args.input);
  const currentPricingFingerprint = pricingFingerprint(args.calculated);
  if (existing) {
    const snapshot = existing.pricingSnapshot as Record<string, any> | null;
    if (snapshot?.automatic?.configurationHash !== hash) {
      return {
        success: false as const,
        code: ERROR_CODES.RESOURCE_ALREADY_EXISTS,
        message:
          "This checkout request id was already used for a different custom-plan configuration.",
      };
    }
    if (snapshot?.automatic?.pricingFingerprint !== currentPricingFingerprint) {
      return {
        success: false as const,
        code: ERROR_CODES.RESOURCE_ALREADY_EXISTS,
        message:
          "Pricing changed since this checkout request was created. Refresh the custom-plan price before retrying checkout.",
      };
    }
    return { success: true as const, quote: existing };
  }

  const c = args.calculated;
  const instant = c.manualReviewReasons!.length === 0;
  const suffix = args.requestId.slice(0, 8);
  const pricingSnapshot = {
    calculatedAt: new Date().toISOString(),
    mode: "automatic-self-service",
    currency: c.policy!.currency,
    vendorRateIds: c.vendorRates!.map((rate) => rate.id),
    vendorBreakdown: c.pricing!.vendorBreakdown,
    warnings: c.pricing!.warnings,
    automatic: {
      configurationHash: hash,
      pricingFingerprint: currentPricingFingerprint,
      eligibleForInstantCheckout: instant,
      manualReviewReasons: c.manualReviewReasons,
      fixedPlatformFee: c.pricing!.fixedPlatformFee.toString(),
      recommendedPrice: c.pricing!.recommendedPrice.toString(),
      roundingIncrement: c.policy!.roundingIncrement,
    },
    fx: c.policy!.fxRate
      ? {
          rate: String(c.policy!.fxRate),
          sourceCurrency: c.policy!.fxSourceCurrency,
          targetCurrency: c.policy!.fxTargetCurrency,
          source: c.policy!.fxSource,
          rateAt: c.policy!.fxRateAt,
        }
      : null,
    inputs: {
      monthlyInfrastructureCost: c.policy!.monthlyInfrastructureCost,
      activePayingTenants: c.policy!.activePayingTenants,
      estimatedOtherCost: c.policy!.estimatedOtherCost,
    },
  };

  const quote = await customPlanRepository.createQuote({
    tenantId: args.tenantId,
    createdBy: args.userId,
    data: {
      id: args.requestId,
      name: `Custom ${suffix}`,
      nameAr: `Custom ${suffix}`,
      description: "Self-service custom plan configuration",
      descriptionAr: "Self-service custom plan configuration",
      status: instant ? "approved" : "calculated",
      currency: c.policy!.currency,
      billingIntervalValue: 1,
      billingIntervalUnit: "month",
      trialPeriodValue: c.policy!.trialPeriodValue,
      billingOptions: c.policy!
        .billingOptions as unknown as Prisma.InputJsonValue,
      estimatedVendorCost: c.pricing!.estimatedVendorCost,
      estimatedInfrastructureCost: c.pricing!.estimatedInfrastructureCost,
      estimatedOtherCost: c.pricing!.estimatedOtherCost,
      estimatedTotalCost: c.pricing!.estimatedTotalCost,
      targetGrossMargin: c.pricing!.targetGrossMargin,
      maxVendorCostRevenueRatio: c.policy!.maxVendorCostRevenueRatio,
      grossMarginFloor: c.pricing!.grossMarginFloor,
      vendorCostRatioFloor: c.pricing!.vendorCostRatioFloor,
      minimumSafePrice: c.pricing!.minimumSafePrice,
      finalPrice: instant ? c.pricing!.recommendedPrice : null,
      fxRate: c.policy!.fxRate == null ? null : decimal(c.policy!.fxRate),
      fxSourceCurrency: c.policy!.fxSourceCurrency,
      fxTargetCurrency: c.policy!.fxTargetCurrency,
      fxSource: c.policy!.fxSource,
      fxRateAt: c.policy!.fxRateAt ? new Date(c.policy!.fxRateAt) : null,
      pricingInputs: {
        monthlyInfrastructureCost: c.policy!.monthlyInfrastructureCost,
        activePayingTenants: c.policy!.activePayingTenants,
        estimatedOtherCost: c.policy!.estimatedOtherCost,
      } as Prisma.InputJsonValue,
      pricingSnapshot: pricingSnapshot as Prisma.InputJsonValue,
      overrideReason: null,
      approvedBy: instant ? args.userId : null,
      expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
    },
    features: c.normalizedFeatures!.map((item) => ({
      featureId: item.featureId,
      limitValue: item.limitValue,
      estimatedUsage: item.estimatedUsage,
      metadata: { source: "self-service" },
    })),
  });

  return { success: true as const, quote };
}

export async function requestCustomPlanManualReview(
  tenantId: string,
  userId: string,
  input: CustomPlanManualReviewInput,
): Promise<ServiceResult<any>> {
  const previewInput: CustomPlanPreviewInput = {
    features: input.features,
    billingPeriod: input.billingPeriod,
  };

  const calculated = await calculateConfiguration(previewInput);
  if (!calculated.result.success) return calculated.result;

  if (calculated.manualReviewReasons!.length === 0) {
    return {
      success: false,
      code: ERROR_CODES.VALIDATION_ERROR,
      message:
        "This configuration is eligible for automatic processing and does not require manual review.",
    };
  }

  const persisted = await createOrReuseAutomaticQuote({
    tenantId,
    userId,
    requestId: input.requestId,
    input: previewInput,
    calculated: calculated as any,
  });
  if (!persisted.success) return persisted;

  return {
    success: true,
    data: {
      manualReviewRequired: true,
      quoteId: persisted.quote.id,
      currency: calculated.policy!.currency,
      billingPeriod: calculated.billingOption!.period,
      previewPrice: calculated.totalPrice,
      reasons: calculated.manualReviewReasons,
    },
    message: "Your custom-plan request was submitted for manual review.",
  };
}

export async function checkoutCustomPlanConfiguration(
  tenantId: string,
  user: { id: string; email: string },
  input: CustomPlanInstantCheckoutInput,
): Promise<ServiceResult<any>> {
  if (input.paymentMethod === "paypal") {
    return {
      success: false,
      code: ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER,
      message: "PayPal is not supported by the current payment integration.",
    };
  }

  // Authoritative checkout-time recalculation. We intentionally do not trust a
  // previewed price or any browser-supplied monetary value.
  const previewInput: CustomPlanPreviewInput = {
    features: input.features,
    billingPeriod: input.billingPeriod,
  };
  const calculated = await calculateConfiguration(previewInput);
  if (!calculated.result.success) return calculated.result;

  const persisted = await createOrReuseAutomaticQuote({
    tenantId,
    userId: user.id,
    requestId: input.requestId,
    input: previewInput,
    calculated: calculated as any,
  });
  if (!persisted.success) return persisted;

  if (calculated.manualReviewReasons!.length > 0) {
    return {
      success: true,
      data: {
        manualReviewRequired: true,
        quoteId: persisted.quote.id,
        currency: calculated.policy!.currency,
        billingPeriod: calculated.billingOption!.period,
        previewPrice: calculated.totalPrice,
        reasons: calculated.manualReviewReasons,
      },
      message: "This configuration requires manual review before checkout.",
    };
  }

  let plan = persisted.quote.createdPlan;
  if (!plan) {
    const accepted = await acceptCustomPlanQuote(tenantId, persisted.quote.id);
    if (!accepted.success) return accepted;
    plan = accepted.data;
  }

  const existingSubscription =
    await subscriptionRepo.getCurrentSubscriptionByTenant(tenantId);
  if (existingSubscription) {
    const changed = await changePlanService(
      plan.id,
      tenantId,
      input.billingPeriod,
    );
    if (!changed.success) return changed;

    return {
      success: true,
      data: {
        manualReviewRequired: false,
        subscriptionChanged: true,
        quoteId: persisted.quote.id,
        planId: plan.id,
        checkoutUrl: null,
        currency: calculated.policy!.currency,
        billingPeriod: calculated.billingOption!.period,
        price: calculated.totalPrice,
        transition: changed.data,
      },
      message:
        changed.message ??
        "Subscription changed to the custom plan successfully.",
    };
  }

  const checkout = await checkoutService(
    {
      planId: plan.id,
      billing_period: input.billingPeriod as any,
      payment_method: input.paymentMethod,
      promoCode: input.promoCode,
    },
    {
      id: user.id,
      email: user.email,
      tenant_id: tenantId,
    },
  );
  if (!checkout.success) return checkout;

  return {
    success: true,
    data: {
      manualReviewRequired: false,
      quoteId: persisted.quote.id,
      planId: plan.id,
      checkoutUrl: checkout.data.checkoutUrl,
      currency: calculated.policy!.currency,
      billingPeriod: calculated.billingOption!.period,
      price: calculated.totalPrice,
    },
  };
}
