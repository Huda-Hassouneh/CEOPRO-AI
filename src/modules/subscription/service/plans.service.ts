import { ERROR_CODES } from "../../../errors/error-codes.js";
import plansRepo from "../repo/plans.repo.js";
import subscriptionRepo from "../repo/subscription.repo.js";
import { getAppConfig } from "../repo/repo.js";
import {
  AppConfig,
  Plan,
  Subscription
} from "../../../generated/prisma/client.js";
import { configKeys } from "../../../config/keys.config.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";
import { PlanBillingOptionType } from "../../../types/plans.js";
import { optionPrice, resolveBillingOption, validatePlanOptions } from "./plan-pricing.js";
import { PlanCreateInput } from "../../../generated/prisma/models.js";

import type { ServiceResult } from "../../../types/service.js";
import {
  analyzePlanTransition,
  type PlanTransitionAnalysis,
  type PlanTransitionTiming,
  type PlanTransitionType
} from "./plan-transition.service.js";

async function archiveUnpublishedPrices(priceIds: string[]) {
  for (const id of priceIds) {
    try {
      await stripeService.stripe.prices.update(id, { active: false });
    } catch (error) {
      console.error(`Failed to archive unpublished Stripe Price ${id}:`, error);
    }
  }
}

export async function getPlansService(): Promise<ServiceResult<Plan[]>> {
  const plans = await plansRepo.getAllPlans();
  return { success: true, data: plans };
}

function normalizePlanForCatalog(plan: any) {
  const basePrice = Number(plan.price);

  const richFeatures = (plan.planFeatures ?? []).reduce(
    (acc: Record<string, any>, pf: any) => {
      if (pf.feature?.code) {
        acc[pf.feature.code] = {
          limitValue: pf.limit_value,
          id: pf.feature.id,
          name: pf.feature.name,
          name_ar: pf.feature.name_ar,
          description: pf.feature.description,
          description_ar: pf.feature.description_ar,
          type: pf.feature.type,
          unit: pf.feature.unit,
          unit_ar: pf.feature.unit_ar
        };
      }
      return acc;
    },
    {}
  );

  const defaultOptions = [
    { period: "monthly", months: 1, discountPercent: 0 },
    { period: "three-months", months: 3, discountPercent: 10 },
    { period: "six-months", months: 6, discountPercent: 20 }
  ];

  const rawOptions = (plan.billingOptions as Array<any>) || defaultOptions;
  const pricingOptions = rawOptions.map((opt) => {
    const resolved = resolveBillingOption(opt);
    const finalPrice = optionPrice(basePrice, plan.billingIntervalValue,
      plan.billingIntervalUnit === "week" ? "month" : plan.billingIntervalUnit, resolved, plan.currency);
    const months = resolved.months;
    return {
      period: opt.period,
      months,
      intervalUnit: resolved.intervalUnit,
      intervalCount: resolved.intervalCount,
      discountPercent: opt.discountPercent,
      totalPrice: finalPrice,
      monthlyEquivalent: months ? Number((finalPrice / months).toFixed(2)) : null,
      stripePriceId: opt?.stripePriceId
    };
  });

  return {
    id: plan.id,
    name: plan.name,
    name_ar: plan.name_ar,
    tier_level: plan.tierLevel,
    planType: plan.planType,
    tenantId: plan.tenantId,
    description: plan.description,
    description_ar: plan.description_ar,
    basePrice,
    billingIntervalValue: plan.billingIntervalValue,
    billingIntervalUnit: plan.billingIntervalUnit,
    currency: plan.currency,
    trialPeriodValue: plan.trialPeriodValue,
    isActive: plan.isActive,
    createdAt: plan.createdAt,
    updatedAt: plan.updatedAt,
    pricingOptions,
    features: richFeatures
  };
}

export async function getPlans() {
  const plans = await plansRepo.getActivePlansWithLimits();
  return plans.map(normalizePlanForCatalog);
}

export async function getManagedStandardPlans() {
  const plans = await plansRepo.getManagedStandardPlansWithLimits();
  return plans.map(normalizePlanForCatalog);
}

export type PlanChangeResult = {
  transitionType: PlanTransitionType;
  effectiveTiming: PlanTransitionTiming;
  effectiveAt: Date | null;
  currentPlan: { id: string; name: string };
  targetPlan: { id: string; name: string };
  priceDelta: number;
  entitlementAnalysis: Pick<
    PlanTransitionAnalysis,
    "hasEntitlementGain" | "hasEntitlementLoss" | "gains" | "losses"
  >;
};

export async function changePlanService(
  planId: string,
  tenantId: string,
  billingPeriod: string
): Promise<ServiceResult<PlanChangeResult>> {
  try {
    const plan = await plansRepo.getPlanById(planId);
    if (!plan) {
      return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
    }

    if (!plan.isActive && plan.planType === "standard") {
      return { success: false, code: ERROR_CODES.PLAN_NOT_AVAILABLE };
    }

    if (plan.planType === "custom" && plan.tenantId !== tenantId) {
      return { success: false, code: ERROR_CODES.PLAN_NOT_AVAILABLE };
    }

    const billingOptions = (plan.billingOptions as any[]) || [];
    const selectedPricingOption = billingOptions.find(
      (opt) => opt.period === billingPeriod
    );

    if (!selectedPricingOption || !selectedPricingOption.stripePriceId) {
      return {
        success: false,
        code: ERROR_CODES.INVALID_BILLING_PERIOD,
        message: `Billing period '${billingPeriod}' is not valid for this plan.`
      };
    }

    const subscription = (await subscriptionRepo.getActiveSubscriptionByTenant(
      tenantId
    )) as Subscription;

    if (!subscription) {
      return { success: false, code: ERROR_CODES.SUBSCRIPTION_NOT_FOUND };
    }

    // SCENARIO 1: Same Plan and Billing Period
    if (
      plan.id === subscription.planId &&
      billingPeriod === subscription.billingPeriod
    ) {
      if (subscription.scheduledPlanId) {
        return {
          success: false,
          code: ERROR_CODES.CANCEL_DOWNGRADE_REQUIRED,
          message:
            "You are already on this plan, but have a downgrade scheduled. Please cancel the pending downgrade to remain on this plan."
        };
      }
      return {
        success: false,
        code: ERROR_CODES.ALREADY_ACTIVE_PLAN,
        message:
          "You are currently actively subscribed to this plan and billing cycle."
      };
    }

    // SCENARIO 2: Already scheduled for this transition
    if (
      subscription.scheduledPlanId === plan.id &&
      subscription.scheduledBillingPeriod === billingPeriod
    ) {
      return {
        success: false,
        code: ERROR_CODES.ALREADY_SCHEDULED_PLAN,
        message:
          "You are already scheduled to transition to this plan and billing cycle at the end of your current term."
      };
    }

    const currentPlan = await plansRepo.getPlanById(subscription.planId);
    if (!currentPlan) {
      return {
        success: false,
        code: ERROR_CODES.PLAN_NOT_FOUND,
        message: "Current subscription plan data not found"
      };
    }

    const currentBillingOptions = (currentPlan.billingOptions as any[]) || [];
    const currentPricingOption = currentBillingOptions.find(
      (opt) => opt.period === subscription.billingPeriod
    ) || { months: 1 };

    const entitlementTransition = analyzePlanTransition(
      currentPlan as any,
      plan as any
    );

    const comparableTiers =
      plan.tierLevel != null && currentPlan.tierLevel != null;

    // Preserve the existing commercial/tier behavior only when entitlement
    // comparison cannot determine a meaningful direction (for example legacy
    // plans with no configured plan_features, or equivalent entitlements).
    const legacyIsUpgrade =
      comparableTiers && plan.tierLevel !== currentPlan.tierLevel
        ? plan.tierLevel! > currentPlan.tierLevel!
        : Number(plan.price) > Number(currentPlan.price)
          ? true
          : Number(plan.price) < Number(currentPlan.price)
            ? false
            : (resolveBillingOption(selectedPricingOption).months ??
                resolveBillingOption(selectedPricingOption).intervalCount) >=
              (resolveBillingOption(currentPricingOption).months ??
                resolveBillingOption(currentPricingOption).intervalCount);

    let effectiveTiming: PlanTransitionTiming;
    let transitionType: PlanTransitionType;

    if (entitlementTransition.comparable && entitlementTransition.type !== "equivalent") {
      transitionType = entitlementTransition.type;
      effectiveTiming = entitlementTransition.recommendedEffectiveTiming;
    } else {
      transitionType = entitlementTransition.comparable
        ? "equivalent"
        : legacyIsUpgrade
          ? "upgrade"
          : "downgrade";
      effectiveTiming = legacyIsUpgrade ? "immediate" : "period_end";
    }

    // Stripe's existing "downgrade" action is really the safe period-end
    // scheduling path. Mixed transitions also use it when any entitlement is
    // being removed/reduced.
    const action = effectiveTiming === "immediate" ? "upgrade" : "downgrade";

    const stripeSubscription = await stripeService.retrieveSubscription(
      subscription.paymentProviderSubscriptionId!
    );
    const isTrialingImmediateChange =
      action === "upgrade" && stripeSubscription.status === "trialing";
    const stripeSubscriptionItemId = stripeSubscription.items.data[0].id;

    await stripeService.updateSubscription({
      paymentProviderPriceId: selectedPricingOption.stripePriceId,
      paymentProviderSubscriptionId: stripeSubscription.id,
      stripeSubscriptionItemId,
      action
    });

    await subscriptionRepo.updateSubscription(subscription.id, {
      scheduledPlanId: effectiveTiming === "period_end" ? plan.id : null,
      scheduledBillingPeriod:
        effectiveTiming === "period_end" ? billingPeriod : null
    });

    const result: PlanChangeResult = {
      transitionType,
      effectiveTiming,
      effectiveAt:
        effectiveTiming === "period_end" ? subscription.currentPeriodEnd : null,
      currentPlan: { id: currentPlan.id, name: currentPlan.name },
      targetPlan: { id: plan.id, name: plan.name },
      priceDelta: Number(plan.price) - Number(currentPlan.price),
      entitlementAnalysis: {
        hasEntitlementGain: entitlementTransition.hasEntitlementGain,
        hasEntitlementLoss: entitlementTransition.hasEntitlementLoss,
        gains: entitlementTransition.gains,
        losses: entitlementTransition.losses
      }
    };

    let message: string;
    if (isTrialingImmediateChange) {
      message =
        "Plan changed successfully. Your current free trial remains unchanged. You will not be charged now; the full new plan price will be charged when the trial ends.";
    } else if (effectiveTiming === "immediate") {
      message =
        plan.planType === "custom"
          ? "Your Custom Plan change has been applied immediately."
          : transitionType === "equivalent"
            ? "Subscription billing cycle changed successfully. Any applicable billing adjustment has been handled by the payment provider."
            : "Subscription upgraded successfully. The applicable prorated amount has been charged.";
    } else if (plan.planType === "custom") {
      message =
        transitionType === "mixed"
          ? `Your Custom Plan has been created successfully and is scheduled to become active at the end of the current billing cycle because some existing entitlements will change or decrease. Your current ${currentPlan.name} plan remains active until then.`
          : `Your Custom Plan has been created successfully and is scheduled to become active at the end of the current billing cycle. Your current ${currentPlan.name} plan remains active until then.`;
    } else {
      message =
        transitionType === "equivalent"
          ? "Billing-cycle change scheduled for the end of the current billing cycle."
          : "Downgrade scheduled for the end of the current billing cycle.";
    }

    return {
      success: true,
      data: result,
      message
    };
  } catch (error) {
    console.error("[Stripe Change Plan Error]:", error);
    return {
      success: false,
      code: ERROR_CODES.PAYMENT_PROVIDER_ERROR
    };
  }
}

export async function createPlansService(
  data: Plan
): Promise<ServiceResult<Plan>> {
  const createdPriceIds: string[] = [];
  try {
    const isPlanExists = await plansRepo.getPlainByName(data.name, false);
    const isPlanExistsAr = await plansRepo.getPlainByName(data.name_ar, true);
    if (isPlanExists || isPlanExistsAr) {
      return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
    }

    const stripeProductKey = (await getAppConfig(
      configKeys.stripeAppConfigKey
    )) as AppConfig;
    const billingOptions = (data.billingOptions ||
      []) as unknown as PlanBillingOptionType[];
    if (billingOptions.length === 0) {
      return {
        success: false,
        code: ERROR_CODES.UNPROCESSABLE_ENTITY,
        message: "At least one billing option must be provided."
      };
    }

    const basePrice = Number(data.price);
    const resolvedOptions = validatePlanOptions(billingOptions, basePrice,
      data.billingIntervalValue, data.billingIntervalUnit, data.currency);
    const updatedBillingOptions: PlanBillingOptionType[] = [];
    const versions = [];

    for (const option of resolvedOptions) {
      const finalPrice = optionPrice(basePrice, data.billingIntervalValue,
        data.billingIntervalUnit, option, data.currency);

      const stripeCreatedPrice = await stripeService.createPlan(
        stripeProductKey?.value,
        {
          name: `${data.name} - ${option.period}`,
          description: data.description || "",
          currency: data.currency,
          unitAmount: finalPrice,
          interval: option.intervalUnit,
          intervalCount: option.intervalCount
        }
      );
      createdPriceIds.push(stripeCreatedPrice.id);

      updatedBillingOptions.push({
        ...option,
        stripePriceId: stripeCreatedPrice.id
      });
      versions.push({ stripePriceId: stripeCreatedPrice.id, period: option.period,
        intervalUnit: option.intervalUnit, intervalCount: option.intervalCount,
        amount: finalPrice, currency: data.currency });
    }

    const insertedPlan = await plansRepo.createPlan({
      ...data,
      billingOptions: updatedBillingOptions as any,
      paymentProviderProductId: stripeProductKey.value,
      paymentProviderPlanId: updatedBillingOptions[0].stripePriceId
    }, versions);

    return { success: true, data: insertedPlan };
  } catch (err) {
    console.error(err);
    await archiveUnpublishedPrices(createdPriceIds);
    return {
      success: false,
      code: ERROR_CODES.UNPROCESSABLE_ENTITY,
      message: err instanceof Error && /Billing option|Invalid plan|Day-based|Stripe interval|Calculated Stripe price/.test(err.message)
        ? err.message : undefined
    };
  }
}

export async function updatePlansService(
  id: string,
  data: PlanCreateInput
): Promise<ServiceResult<any>> {
  const existingPlan = await plansRepo.getPlanById(id);
  if (!existingPlan) {
    return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
  }

  // Accepted custom plans are commercial snapshots. They must not be
  // destructively edited through the generic public-catalog endpoint.
  // Create a new custom quote/version instead.
  if (existingPlan.planType === "custom") {
    return {
      success: false,
      code: ERROR_CODES.PLAN_NOT_AVAILABLE,
      message:
        "Accepted custom plans are immutable. Create a new custom plan quote to change terms."
    };
  }

  if (data.name) {
    const planWithSameName = await plansRepo.getPlainByName(data.name, false);
    const planWithSameNameAr = await plansRepo.getPlainByName(data.name, true);

    if (
      (planWithSameName && planWithSameName.id !== id) ||
      (planWithSameNameAr && planWithSameNameAr.id !== id)
    ) {
      return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
    }
  }

  const createdPriceIds: string[] = [];
  try {
  let versions: Array<{ stripePriceId: string; period: string; intervalUnit: string;
    intervalCount: number; amount: number; currency: string }> | undefined;
  if (data.billingOptions || data.price !== undefined || data.currency ||
      data.billingIntervalValue !== undefined || data.billingIntervalUnit) {
    const stripeProductKey = (await getAppConfig(
      configKeys.stripeAppConfigKey
    )) as AppConfig;
    const basePrice = Number(data.price ?? existingPlan.price);
    const baseIntervalValue = data.billingIntervalValue ?? existingPlan.billingIntervalValue;
    const baseIntervalUnit = data.billingIntervalUnit ?? existingPlan.billingIntervalUnit;
    const currency = data.currency ?? existingPlan.currency;
    const incomingOptions = (data.billingOptions ||
      existingPlan.billingOptions) as unknown as PlanBillingOptionType[];
    const existingOptions =
      (existingPlan.billingOptions as unknown as PlanBillingOptionType[]) || [];
    let resolvedOptions;
    try {
      resolvedOptions = validatePlanOptions(incomingOptions, basePrice,
        baseIntervalValue, baseIntervalUnit, currency);
    } catch (error) {
      return { success: false, code: ERROR_CODES.UNPROCESSABLE_ENTITY,
        message: (error as Error).message };
    }
    const updatedBillingOptions: PlanBillingOptionType[] = [];
    versions = [];

    for (const oldOption of existingOptions) {
      if (!oldOption.stripePriceId) continue;
      const resolved = resolveBillingOption(oldOption);
      versions.push({ stripePriceId: oldOption.stripePriceId,
        period: resolved.period, intervalUnit: resolved.intervalUnit,
        intervalCount: resolved.intervalCount,
        amount: optionPrice(Number(existingPlan.price), existingPlan.billingIntervalValue,
          existingPlan.billingIntervalUnit === "week" ? "month" : existingPlan.billingIntervalUnit, resolved, existingPlan.currency),
        currency: existingPlan.currency });
    }

    for (const option of resolvedOptions) {
      const finalPrice = optionPrice(basePrice, baseIntervalValue, baseIntervalUnit, option, currency);

      const oldOption = existingOptions.find((o) => o.period === option.period);
      const oldResolved = oldOption ? resolveBillingOption(oldOption) : null;
      const oldFinalPrice = oldResolved ? optionPrice(Number(existingPlan.price),
        existingPlan.billingIntervalValue,
        existingPlan.billingIntervalUnit === "week" ? "month" : existingPlan.billingIntervalUnit,
        oldResolved, existingPlan.currency) : null;

      let stripePriceId = oldOption?.stripePriceId;

      if (!stripePriceId || finalPrice !== oldFinalPrice ||
          option.intervalUnit !== oldResolved?.intervalUnit ||
          option.intervalCount !== oldResolved?.intervalCount ||
          currency !== existingPlan.currency) {
        const stripeCreatedPrice = await stripeService.createPlan(
          existingPlan.paymentProviderProductId || stripeProductKey?.value,
          {
            name: `${data.name || existingPlan.name} - ${option.period}`,
            description: data.description || existingPlan.description || "",
            currency,
            unitAmount: finalPrice,
            interval: option.intervalUnit,
            intervalCount: option.intervalCount
          }
        );
        createdPriceIds.push(stripeCreatedPrice.id);
        stripePriceId = stripeCreatedPrice.id;
      }

      updatedBillingOptions.push({
        ...option,
        stripePriceId
      });
      versions.push({ stripePriceId, period: option.period,
        intervalUnit: option.intervalUnit, intervalCount: option.intervalCount,
        amount: finalPrice, currency });
    }

    data.billingOptions = updatedBillingOptions as any;

    if (updatedBillingOptions.length > 0) {
      data.paymentProviderPlanId = updatedBillingOptions[0].stripePriceId;
    }
  }

  const plan = await plansRepo.updatePlan(id, data, versions);
  return { success: true, data: plan };
  } catch (error) {
    console.error("Plan update failed:", error);
    await archiveUnpublishedPrices(createdPriceIds);
    return { success: false, code: ERROR_CODES.UNPROCESSABLE_ENTITY };
  }
}
