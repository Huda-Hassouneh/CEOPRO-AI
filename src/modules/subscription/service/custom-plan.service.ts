import { Prisma } from "../../../generated/prisma/client.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { ServiceResult } from "../../../types/service.js";
import type {
  ApproveCustomPlanQuoteInput,
  CreateCustomPlanQuoteInput,
  UpdateCustomPlanQuoteInput,
  VendorRateInput,
} from "../../../DTO/customPlan.dto.js";
import {
  CUSTOM_PLAN_PAYMENT_CURRENCY,
  convertCustomPlanAmountToPaymentCurrency,
} from "./custom-plan-payment-currency.service.js";
import customPlanRepository from "../repo/custom-plan.repo.js";
import {
  calculateCustomPlanPrice,
  calculateExpectedProfitability,
} from "./custom-plan-pricing.service.js";
import { getAppConfig } from "../repo/repo.js";
import { configKeys } from "../../../config/keys.config.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import type { BillingOptionType } from "../../../types/plans.js";
import { getCustomPlanPricingPolicy } from "./custom-plan-policy.service.js";

const EDITABLE_STATUSES = new Set(["draft", "calculated"]);
const SENDABLE_STATUS = "approved";
const ACCEPTABLE_STATUSES = new Set(["approved", "sent"]);

type DecimalInput = ConstructorParameters<typeof Prisma.Decimal>[0];

function decimal(value: DecimalInput) {
  return new Prisma.Decimal(value);
}
function priceWithDiscount(
  basePrice: number,
  months: number,
  discountPercent: number,
) {
  return Number(
    (basePrice * months * (1 - (discountPercent || 0) / 100)).toFixed(2),
  );
}

function normalizeQuote(quote: any) {
  if (!quote) return quote;
  const numberFields = [
    "estimatedVendorCost",
    "estimatedInfrastructureCost",
    "estimatedOtherCost",
    "estimatedTotalCost",
    "targetGrossMargin",
    "maxVendorCostRevenueRatio",
    "grossMarginFloor",
    "vendorCostRatioFloor",
    "minimumSafePrice",
    "finalPrice",
    "fxRate",
  ];
  const normalized: any = { ...quote };
  for (const field of numberFields) {
    if (normalized[field] != null)
      normalized[field] = Number(normalized[field]);
  }
  if (Array.isArray(normalized.quoteFeatures)) {
    normalized.quoteFeatures = normalized.quoteFeatures.map((item: any) => ({
      ...item,
      estimatedUsage: Number(item.estimatedUsage),
    }));
  }
  if (normalized.createdPlan?.price != null) {
    normalized.createdPlan = {
      ...normalized.createdPlan,
      price: Number(normalized.createdPlan.price),
    };
  }
  const snapshot = normalized.pricingSnapshot;
  if (snapshot && typeof snapshot === "object" && !Array.isArray(snapshot)) {
    const automatic = (snapshot as Record<string, any>).automatic;
    const recommended =
      automatic?.recommendedPrice ??
      (snapshot as Record<string, any>).recommendedPrice;
    if (recommended != null) normalized.recommendedPrice = Number(recommended);
  }
  return normalized;
}

async function validateQuoteFeatures(
  features: Array<{ featureId: string; limitValue?: number | null }>,
) {
  const uniqueIds = [...new Set(features.map((feature) => feature.featureId))];
  if (uniqueIds.length !== features.length) {
    return {
      success: false as const,
      code: ERROR_CODES.VALIDATION_ERROR,
      message: "Duplicate features are not allowed.",
    };
  }

  const existing = await customPlanRepository.getFeaturesByIds(uniqueIds);
  if (existing.length !== uniqueIds.length) {
    return {
      success: false as const,
      code: ERROR_CODES.RESOURCE_NOT_FOUND,
      message: "One or more selected features do not exist.",
    };
  }

  const byId = new Map(existing.map((feature) => [feature.id, feature]));
  for (const feature of features) {
    const definition = byId.get(feature.featureId)!;
    if (definition.type === "boolean" && feature.limitValue != null) {
      return {
        success: false as const,
        code: ERROR_CODES.INVALID_PARAMETER,
        message: `Boolean feature '${definition.code}' cannot have a numeric limit.`,
      };
    }
  }
  return { success: true as const };
}

type PricingInputsSource = Partial<
  Pick<
    CreateCustomPlanQuoteInput,
    "monthlyInfrastructureCost" | "activePayingTenants" | "estimatedOtherCost"
  >
>;

function buildPricingInputs(
  input: PricingInputsSource,
  previous: Record<string, any> = {},
) {
  return {
    monthlyInfrastructureCost:
      input.monthlyInfrastructureCost ??
      previous.monthlyInfrastructureCost ??
      0,
    activePayingTenants:
      input.activePayingTenants ?? previous.activePayingTenants ?? 1,
    estimatedOtherCost:
      input.estimatedOtherCost ?? previous.estimatedOtherCost ?? 0,
  };
}

function quoteDbData(input: CreateCustomPlanQuoteInput, createdBy?: string) {
  return {
    name: input.name,
    nameAr: input.name_ar,
    description: input.description ?? null,
    descriptionAr: input.description_ar ?? null,
    currency: input.currency,
    billingIntervalValue: input.billingIntervalValue,
    billingIntervalUnit: input.billingIntervalUnit,
    trialPeriodValue: input.trialPeriodValue,
    billingOptions: input.billingOptions as unknown as Prisma.InputJsonValue,
    targetGrossMargin: decimal(input.targetGrossMargin),
    maxVendorCostRevenueRatio: decimal(input.maxVendorCostRevenueRatio),
    fxRate: input.fxRate != null ? decimal(input.fxRate) : null,
    fxSourceCurrency: input.fxSourceCurrency ?? null,
    fxTargetCurrency: input.fxTargetCurrency ?? null,
    fxSource: input.fxSource ?? null,
    fxRateAt: input.fxRateAt ? new Date(input.fxRateAt) : null,
    expiresAt: input.expiresAt ? new Date(input.expiresAt) : null,
    pricingInputs: buildPricingInputs(input) as Prisma.InputJsonValue,
    createdBy: createdBy ?? null,
    status: "draft" as const,
    finalPrice: null,
    overrideReason: null,
    approvedBy: null,
    pricingSnapshot: Prisma.JsonNull,
  };
}

export async function createCustomPlanQuote(
  tenantId: string,
  userId: string,
  input: CreateCustomPlanQuoteInput,
): Promise<ServiceResult<any>> {
  const featureValidation = await validateQuoteFeatures(input.features);
  if (!featureValidation.success) return featureValidation;

  const quote = await customPlanRepository.createQuote({
    tenantId,
    createdBy: userId,
    data: quoteDbData(input, userId),
    features: input.features,
  });

  return { success: true, data: normalizeQuote(quote) };
}

export async function listCustomPlanQuotes(
  tenantId: string,
): Promise<ServiceResult<any[]>> {
  const quotes = await customPlanRepository.listQuotesForTenant(tenantId);
  return { success: true, data: quotes.map(normalizeQuote) };
}

export async function listPlatformCustomPlanQuotes(): Promise<
  ServiceResult<any[]>
> {
  const quotes = await customPlanRepository.listAllQuotes();
  return { success: true, data: quotes.map(normalizeQuote) };
}

export async function getPlatformCustomPlanQuote(
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteById(id);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  return { success: true, data: normalizeQuote(quote) };
}

export async function listPlatformTenants(): Promise<ServiceResult<any[]>> {
  return {
    success: true,
    data: await customPlanRepository.listPlatformTenants(),
  };
}

export async function getCustomPlanQuote(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  return { success: true, data: normalizeQuote(quote) };
}

export async function getCustomPlanOffer(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (!["approved", "sent", "accepted"].includes(quote.status)) {
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };
  }
  if (
    quote.expiresAt &&
    quote.expiresAt.getTime() <= Date.now() &&
    quote.status !== "accepted"
  ) {
    return {
      success: false,
      code: ERROR_CODES.INVALID_QUOTE_STATUS,
      message: "This custom plan offer has expired.",
    };
  }

  return {
    success: true,
    data: {
      id: quote.id,
      name: quote.name,
      name_ar: quote.nameAr,
      description: quote.description,
      description_ar: quote.descriptionAr,
      status: quote.status,
      currency: quote.currency,
      finalPrice: quote.finalPrice == null ? null : Number(quote.finalPrice),
      billingIntervalValue: quote.billingIntervalValue,
      billingIntervalUnit: quote.billingIntervalUnit,
      billingOptions: quote.billingOptions,
      trialPeriodValue: quote.trialPeriodValue,
      expiresAt: quote.expiresAt,
      createdPlanId: quote.createdPlanId,
      features: quote.quoteFeatures.map((item) => ({
        featureId: item.featureId,
        limitValue: item.limitValue,
        feature: item.feature,
      })),
    },
  };
}

export async function updateCustomPlanQuote(
  tenantId: string,
  id: string,
  input: UpdateCustomPlanQuoteInput,
): Promise<ServiceResult<any>> {
  const existing = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!existing)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (!EDITABLE_STATUSES.has(existing.status))
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };

  if (input.features) {
    const featureValidation = await validateQuoteFeatures(input.features);
    if (!featureValidation.success) return featureValidation;
  }

  const previousPricingInputs =
    (existing.pricingInputs as Record<string, any> | null) ?? {};
  const pricingInputPatch = buildPricingInputs(input, previousPricingInputs);
  const data: Record<string, any> = {
    status: "draft",
    pricingSnapshot: Prisma.JsonNull,
    finalPrice: null,
    overrideReason: null,
    approvedBy: null,
    pricingInputs: pricingInputPatch as Prisma.InputJsonValue,
  };

  const direct: Record<string, any> = {
    name: input.name,
    nameAr: input.name_ar,
    description: input.description,
    descriptionAr: input.description_ar,
    currency: input.currency,
    billingIntervalValue: input.billingIntervalValue,
    billingIntervalUnit: input.billingIntervalUnit,
    trialPeriodValue: input.trialPeriodValue,
    billingOptions: input.billingOptions as unknown as
      | Prisma.InputJsonValue
      | undefined,
    targetGrossMargin:
      input.targetGrossMargin != null
        ? decimal(input.targetGrossMargin)
        : undefined,
    maxVendorCostRevenueRatio:
      input.maxVendorCostRevenueRatio != null
        ? decimal(input.maxVendorCostRevenueRatio)
        : undefined,
    fxRate:
      input.fxRate === null
        ? null
        : input.fxRate != null
          ? decimal(input.fxRate)
          : undefined,
    fxSourceCurrency: input.fxSourceCurrency,
    fxTargetCurrency: input.fxTargetCurrency,
    fxSource: input.fxSource,
    fxRateAt:
      input.fxRateAt === null
        ? null
        : input.fxRateAt
          ? new Date(input.fxRateAt)
          : undefined,
    expiresAt:
      input.expiresAt === null
        ? null
        : input.expiresAt
          ? new Date(input.expiresAt)
          : undefined,
  };
  for (const [key, value] of Object.entries(direct))
    if (value !== undefined) data[key] = value;

  const updated = await customPlanRepository.updateDraftQuote({
    id,
    tenantId,
    data,
    features: input.features,
  });
  return updated
    ? { success: true, data: normalizeQuote(updated) }
    : { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
}

export async function calculateCustomPlanQuote(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (!EDITABLE_STATUSES.has(quote.status))
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };

  const pricingInputs =
    (quote.pricingInputs as Record<string, any> | null) ?? {};
  const featureIds = quote.quoteFeatures.map((item) => item.featureId);
  const [vendorRates, vendorBackedFeatureIds, policy] = await Promise.all([
    customPlanRepository.getActiveVendorRates(featureIds),
    customPlanRepository.getVendorBackedFeatureIds(featureIds),
    getCustomPlanPricingPolicy(),
  ]);
  const vendorBacked = new Set(vendorBackedFeatureIds);

  try {
    const result = calculateCustomPlanPrice({
      quoteCurrency: quote.currency,

      features: quote.quoteFeatures.map((item) => ({
        featureId: item.featureId,
        estimatedUsage:
          item.feature.type === "boolean"
            ? vendorBacked.has(item.featureId)
              ? 1
              : 0
            : item.estimatedUsage,
      })),

      vendorRates,
      vendorCostRequiredFeatureIds: vendorBackedFeatureIds,
      monthlyInfrastructureCost: pricingInputs.monthlyInfrastructureCost ?? 0,
      activePayingTenants: Number(pricingInputs.activePayingTenants ?? 1),
      estimatedOtherCost: pricingInputs.estimatedOtherCost ?? 0,
      targetGrossMargin: quote.targetGrossMargin,
      maxVendorCostRevenueRatio: quote.maxVendorCostRevenueRatio,
      enforceVendorCostRatioFloor: policy.enforceVendorCostRatioFloor,
      fixedPlatformFee: policy.fixedPlatformFee,
      roundingIncrement: policy.roundingIncrement,
      fxRate: quote.fxRate,
      fxSourceCurrency: quote.fxSourceCurrency,
      fxTargetCurrency: quote.fxTargetCurrency,
    });

    const pricingSnapshot = {
      calculatedAt: new Date().toISOString(),
      currency: quote.currency,
      vendorRateIds: vendorRates.map((rate) => rate.id),
      vendorBreakdown: result.vendorBreakdown,
      warnings: result.warnings,
      fx: quote.fxRate
        ? {
            rate: quote.fxRate.toString(),
            sourceCurrency: quote.fxSourceCurrency,
            targetCurrency: quote.fxTargetCurrency,
            source: quote.fxSource,
            rateAt: quote.fxRateAt?.toISOString() ?? null,
          }
        : null,
      inputs: pricingInputs,
      pricingPolicy: {
        enforceVendorCostRatioFloor: policy.enforceVendorCostRatioFloor,
        fixedPlatformFee: result.fixedPlatformFee.toString(),
        roundingIncrement: policy.roundingIncrement,
      },
      recommendedPrice: result.recommendedPrice.toString(),
    };

    const updated = await customPlanRepository.updateQuote(quote.id, {
      status: "calculated",
      estimatedVendorCost: result.estimatedVendorCost,
      estimatedInfrastructureCost: result.estimatedInfrastructureCost,
      estimatedOtherCost: result.estimatedOtherCost,
      estimatedTotalCost: result.estimatedTotalCost,
      grossMarginFloor: result.grossMarginFloor,
      vendorCostRatioFloor: result.vendorCostRatioFloor,
      minimumSafePrice: result.minimumSafePrice,
      pricingSnapshot: pricingSnapshot as Prisma.InputJsonValue,
    });

    return { success: true, data: normalizeQuote(updated) };
  } catch (error) {
    const message = (error as Error).message;
    if (message.startsWith("Missing FX rate")) {
      return { success: false, code: ERROR_CODES.FX_RATE_REQUIRED, message };
    }
    if (message.startsWith("Missing vendor rate")) {
      return {
        success: false,
        code: ERROR_CODES.VENDOR_RATE_REQUIRED,
        message,
      };
    }
    return { success: false, code: ERROR_CODES.VALIDATION_ERROR, message };
  }
}

export async function approveCustomPlanQuote(
  tenantId: string,
  id: string,
  userId: string,
  input: ApproveCustomPlanQuoteInput,
  canOverrideSafePrice: boolean,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (quote.status !== "calculated")
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };

  const finalPrice = decimal(input.finalPrice);
  const belowFloor = finalPrice.lessThan(quote.minimumSafePrice);
  if (belowFloor && (!canOverrideSafePrice || !input.overrideReason)) {
    return { success: false, code: ERROR_CODES.UNSAFE_CUSTOM_PLAN_PRICE };
  }

  const profitability = calculateExpectedProfitability(
    finalPrice,
    quote.estimatedTotalCost,
    quote.estimatedVendorCost,
  );

  const snapshot = {
    ...((quote.pricingSnapshot as Record<string, any> | null) ?? {}),
    approval: {
      approvedAt: new Date().toISOString(),
      finalPrice: finalPrice.toString(),
      minimumSafePrice: quote.minimumSafePrice.toString(),
      expectedGrossMargin: profitability.expectedGrossMargin.toString(),
      expectedVendorCostRatio: profitability.expectedVendorCostRatio.toString(),
      overrideUsed: belowFloor,
      overrideReason: belowFloor ? input.overrideReason : null,
    },
  };

  const updated = await customPlanRepository.updateQuote(quote.id, {
    status: "approved",
    finalPrice,
    approvedBy: userId,
    overrideReason: belowFloor ? input.overrideReason : null,
    pricingSnapshot: snapshot as Prisma.InputJsonValue,
  });
  return { success: true, data: normalizeQuote(updated) };
}

export async function sendCustomPlanQuote(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (quote.status !== SENDABLE_STATUS)
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };
  const updated = await customPlanRepository.updateQuote(id, {
    status: "sent",
  });
  return { success: true, data: normalizeQuote(updated) };
}

export async function rejectCustomPlanQuote(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (["accepted", "rejected", "expired"].includes(quote.status))
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };
  const updated = await customPlanRepository.updateQuote(id, {
    status: "rejected",
  });
  return { success: true, data: normalizeQuote(updated) };
}

export async function acceptCustomPlanQuote(
  tenantId: string,
  id: string,
): Promise<ServiceResult<any>> {
  const quote = await customPlanRepository.findQuoteForTenant(id, tenantId);
  if (!quote)
    return { success: false, code: ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND };
  if (quote.status === "accepted" && quote.createdPlan) {
    return {
      success: true,
      data: normalizeQuote(quote.createdPlan),
      message: "Quote was already accepted.",
    };
  }
  if (!ACCEPTABLE_STATUSES.has(quote.status))
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };
  if (quote.expiresAt && quote.expiresAt.getTime() <= Date.now()) {
    await customPlanRepository.updateQuote(id, { status: "expired" });
    return {
      success: false,
      code: ERROR_CODES.INVALID_QUOTE_STATUS,
      message: "This quote has expired.",
    };
  }
  if (quote.finalPrice == null)
    return { success: false, code: ERROR_CODES.INVALID_QUOTE_STATUS };

  const stripeProductKey = await getAppConfig(configKeys.stripeAppConfigKey);
  if (!stripeProductKey?.value)
    return { success: false, code: ERROR_CODES.PAYMENT_PROVIDER_ERROR };

  const rawOptions = quote.billingOptions as unknown as BillingOptionType[];
  const billingOptions = rawOptions.length
    ? rawOptions
    : [{ period: "monthly", months: 1, discountPercent: 0 }];

  const finalBasePrice = Number(quote.finalPrice);
  const providerOptions: BillingOptionType[] = [];

  try {
    for (const option of billingOptions) {
      /*
       * Commercial amount remains in the quote's currency.
       *
       * Example:
       * 100 JOD
       */
      const quoteAmount = priceWithDiscount(
        finalBasePrice,
        option.months,
        option.discountPercent,
      );

      /*
       * Convert ONLY at the payment-provider boundary.
       *
       * Example:
       *
       * 100 JOD
       * /
       * 0.709 JOD per USD
       * =
       * 141.04 USD
       */
      const paymentAmount = convertCustomPlanAmountToPaymentCurrency({
        amount: quoteAmount,

        quoteCurrency: quote.currency,

        /*
         * IMPORTANT:
         *
         * Use the FX snapshot already stored on the quote.
         * Do NOT read today's policy rate here.
         *
         * This preserves the commercial calculation that
         * the customer actually agreed to.
         */
        fxRate: quote.fxRate,

        fxSourceCurrency: quote.fxSourceCurrency,

        fxTargetCurrency: quote.fxTargetCurrency,
      });

      const providerPrice = await stripeService.createPlan(
        stripeProductKey.value,
        {
          name: `${quote.name} - ${option.period}`,

          description: quote.description ?? "",

          /*
           * IMPORTANT:
           *
           * Stripe receives USD, NOT JOD.
           */
          currency: CUSTOM_PLAN_PAYMENT_CURRENCY,

          /*
           * This is already converted to USD major units.
           *
           * Example:
           * 141.04
           *
           * stripeService will convert that to:
           * 14104 cents
           */
          unitAmount: paymentAmount,

          interval: "month",

          intervalCount: option.months,

          /*
           * Change the key because the old attempt used JOD.
           */
          idempotencyKey: `custom-quote:${quote.id}:${option.period}:${CUSTOM_PLAN_PAYMENT_CURRENCY.toLowerCase()}`,
        },
      );

      providerOptions.push({
        ...option,
        stripePriceId: providerPrice.id,
      });
    }

    const plan = await customPlanRepository.convertQuoteToPlan({
      quoteId: quote.id,
      tenantId,

      paymentProviderProductId: stripeProductKey.value,

      paymentProviderPlanId: providerOptions[0].stripePriceId!,

      billingOptions: providerOptions as unknown as Prisma.InputJsonValue,
    });

    if (!plan) {
      const current = await customPlanRepository.findQuoteForTenant(
        id,
        tenantId,
      );

      if (current?.createdPlan) {
        return {
          success: true,
          data: normalizeQuote(current.createdPlan),
        };
      }

      return {
        success: false,
        code: ERROR_CODES.INVALID_QUOTE_STATUS,
      };
    }

    return {
      success: true,
      data: normalizeQuote(plan),
    };
  } catch (error) {
    console.error("Custom plan quote conversion failed:", error);

    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_ERROR,
    };
  }
}

function normalizeCustomPlan(plan: any) {
  const currentSubscription = plan.activeSubscriptions?.[0] ?? null;
  const scheduledSubscription = plan.scheduledSubscriptions?.[0] ?? null;
  const subscriptionRelationship = currentSubscription
    ? "current"
    : scheduledSubscription
      ? "scheduled"
      : "not_subscribed";

  return {
    id: plan.id,
    name: plan.name,
    name_ar: plan.name_ar,
    description: plan.description,
    description_ar: plan.description_ar,
    planType: plan.planType,
    tenantId: plan.tenantId,
    tenant: plan.tenant ?? undefined,
    sourceQuote: plan.sourceQuote ?? undefined,
    basePrice: Number(plan.price),
    currency: plan.currency,
    trialPeriodValue: plan.trialPeriodValue,
    billingOptions: plan.billingOptions,
    pricingOptions: (
      (plan.billingOptions as unknown as BillingOptionType[]) || []
    ).map((option) => {
      const totalPrice = priceWithDiscount(
        Number(plan.price),
        option.months,
        option.discountPercent,
      );
      return {
        ...option,
        totalPrice,
        monthlyEquivalent: Number((totalPrice / option.months).toFixed(2)),
      };
    }),
    // isActive is the plan definition lifecycle only. It does not mean the
    // tenant's subscription currently points at this plan.
    isActive: plan.isActive,
    planState: plan.isActive ? "enabled" : "disabled",
    subscriptionRelationship,
    subscriptionEffectiveAt:
      subscriptionRelationship === "scheduled"
        ? scheduledSubscription.currentPeriodEnd
        : null,
    currentSubscription: currentSubscription
      ? {
          id: currentSubscription.id,
          status: currentSubscription.status,
          billingPeriod: currentSubscription.billingPeriod,
          currentPeriodEnd: currentSubscription.currentPeriodEnd
        }
      : null,
    scheduledSubscription: scheduledSubscription
      ? {
          id: scheduledSubscription.id,
          status: scheduledSubscription.status,
          currentPlan: scheduledSubscription.plan,
          currentPeriodEnd: scheduledSubscription.currentPeriodEnd,
          scheduledBillingPeriod: scheduledSubscription.scheduledBillingPeriod
        }
      : null,
    createdAt: plan.createdAt,
    updatedAt: plan.updatedAt,
    features: Object.fromEntries(
      (plan.planFeatures ?? []).map((link: any) => [
        link.feature.code,
        { ...link.feature, limitValue: link.limit_value },
      ]),
    ),
  };
}

export async function listTenantCustomPlans(
  tenantId: string,
): Promise<ServiceResult<any[]>> {
  const plans = await customPlanRepository.listCustomPlansForTenant(tenantId);
  return { success: true, data: plans.map(normalizeCustomPlan) };
}

export async function listPlatformCustomPlans(): Promise<ServiceResult<any[]>> {
  const plans = await customPlanRepository.listAllCustomPlans();
  return { success: true, data: plans.map(normalizeCustomPlan) };
}

export async function setPlatformCustomPlanActiveState(
  id: string,
  isActive: boolean,
): Promise<ServiceResult<any>> {
  const plan = await customPlanRepository.setCustomPlanActiveState(
    id,
    isActive,
  );
  if (!plan) return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
  return { success: true, data: normalizeCustomPlan(plan) };
}

export async function listVendorRates(): Promise<ServiceResult<any[]>> {
  const rates = await customPlanRepository.listVendorRates();
  return {
    success: true,
    data: rates.map((rate) => ({
      ...rate,
      unitCost: Number(rate.unitCost),
      operationalMultiplier: Number(rate.operationalMultiplier),
      variabilityReserve: Number(rate.variabilityReserve),
    })),
  };
}

export async function createVendorRate(
  input: VendorRateInput,
): Promise<ServiceResult<any>> {
  if (input.featureId) {
    const features = await customPlanRepository.getFeaturesByIds([
      input.featureId,
    ]);
    if (!features.length)
      return { success: false, code: ERROR_CODES.RESOURCE_NOT_FOUND };
  }
  const rate = await customPlanRepository.createVendorRate({
    ...input,
    featureId: input.featureId ?? null,
    unitCost: decimal(input.unitCost),
    operationalMultiplier: decimal(input.operationalMultiplier),
    variabilityReserve: decimal(input.variabilityReserve),
    effectiveFrom: input.effectiveFrom
      ? new Date(input.effectiveFrom)
      : new Date(),
    effectiveTo: input.effectiveTo ? new Date(input.effectiveTo) : null,
    metadata: input.metadata as Prisma.InputJsonValue | undefined,
  });
  return {
    success: true,
    data: {
      ...rate,
      unitCost: Number(rate.unitCost),
      operationalMultiplier: Number(rate.operationalMultiplier),
      variabilityReserve: Number(rate.variabilityReserve),
    },
  };
}

export async function updateVendorRate(
  id: string,
  input: Partial<VendorRateInput>,
): Promise<ServiceResult<any>> {
  if (input.featureId) {
    const features = await customPlanRepository.getFeaturesByIds([
      input.featureId,
    ]);
    if (!features.length)
      return { success: false, code: ERROR_CODES.RESOURCE_NOT_FOUND };
  }
  try {
    const data: Record<string, any> = { ...input };
    if (input.unitCost != null) data.unitCost = decimal(input.unitCost);
    if (input.operationalMultiplier != null)
      data.operationalMultiplier = decimal(input.operationalMultiplier);
    if (input.variabilityReserve != null)
      data.variabilityReserve = decimal(input.variabilityReserve);
    if (input.effectiveFrom) data.effectiveFrom = new Date(input.effectiveFrom);
    if (input.effectiveTo !== undefined)
      data.effectiveTo = input.effectiveTo ? new Date(input.effectiveTo) : null;
    if (input.metadata) data.metadata = input.metadata as Prisma.InputJsonValue;
    const rate = await customPlanRepository.updateVendorRate(id, data);
    return {
      success: true,
      data: {
        ...rate,
        unitCost: Number(rate.unitCost),
        operationalMultiplier: Number(rate.operationalMultiplier),
        variabilityReserve: Number(rate.variabilityReserve),
      },
    };
  } catch (error: any) {
    if (error?.code === "P2025")
      return { success: false, code: ERROR_CODES.VENDOR_RATE_NOT_FOUND };
    throw error;
  }
}
