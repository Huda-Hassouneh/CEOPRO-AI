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
import { BillingOptionType } from "../../../types/plans.js";
import { PlanCreateInput } from "../../../generated/prisma/models.js";

export type ServiceResult<T> =
  | { success: true; data: T; message?: string }
  | { success: false; code: string; message?: string };

// Helper: Centralize the discount math used across multiple services
function calculateDiscountedPrice(
  basePrice: number,
  months: number,
  discountPercent: number
): number {
  const rawTotal = basePrice * months;
  const discountAmount = rawTotal * ((discountPercent || 0) / 100);
  return rawTotal - discountAmount;
}

export async function getPlansService(): Promise<ServiceResult<Plan[]>> {
  const plans = await plansRepo.getAllPlans();
  return { success: true, data: plans };
}

export async function getPlans() {
  const plans = await plansRepo.getActivePlansWithLimits();

  return plans.map((plan) => {
    const basePrice = Number(plan.price);

    const richFeatures = plan.planFeatures.reduce(
      (acc: Record<string, any>, pf) => {
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
      const finalPrice = calculateDiscountedPrice(
        basePrice,
        opt.months,
        opt.discountPercent
      );

      return {
        period: opt.period,
        months: opt.months,
        discountPercent: opt.discountPercent,
        totalPrice: Number(finalPrice.toFixed(2)),
        monthlyEquivalent: Number((finalPrice / opt.months).toFixed(2)),
        stripePriceId: opt?.stripePriceId
      } as BillingOptionType;
    });

    return {
      id: plan.id,
      name: plan.name,
      name_ar: plan.name_ar,
      tier_level: plan.tierLevel,
      description: plan.description,
      description_ar: plan.description_ar,
      basePrice: basePrice,
      currency: plan.currency,
      trialPeriodValue: plan.trialPeriodValue,
      isActive: plan.isActive,
      pricingOptions,
      features: richFeatures
    };
  });
}

export async function changePlanService(
  planId: string,
  tenantId: string,
  billingPeriod: string
): Promise<ServiceResult<null>> {
  try {
    const plan = await plansRepo.getPlanById(planId);
    if (!plan) {
      return { success: false, code: ERROR_CODES.PLAN_NOT_FOUND };
    }

    const billingOptions = (plan.billingOptions as any[]) || [];
    const selectedPricingOption = billingOptions.find(
      (opt) => opt.period === billingPeriod
    );

    if (!selectedPricingOption || !selectedPricingOption.stripePriceId) {
      return {
        success: false,
        code: "INVALID_BILLING_PERIOD",
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
          code: "CANCEL_DOWNGRADE_REQUIRED",
          message:
            "You are already on this plan, but have a downgrade scheduled. Please cancel the pending downgrade to remain on this plan."
        };
      }
      return {
        success: false,
        code: "ALREADY_ACTIVE_PLAN",
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
        code: "ALREADY_SCHEDULED_PLAN",
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

    const isUpgrade =
      plan.tierLevel !== currentPlan.tierLevel
        ? plan.tierLevel > currentPlan.tierLevel
        : selectedPricingOption.months >= currentPricingOption.months;

    const action = isUpgrade ? "upgrade" : "downgrade";

    const stripeSubscription = await stripeService.retrieveSubscription(
      subscription.paymentProviderSubscriptionId!
    );
    const stripeSubscriptionItemId = stripeSubscription.items.data[0].id;

    await stripeService.updateSubscription({
      paymentProviderPriceId: selectedPricingOption.stripePriceId,
      paymentProviderSubscriptionId: stripeSubscription.id,
      stripeSubscriptionItemId,
      action
    });

    await subscriptionRepo.updateSubscription(subscription.id, {
      scheduledPlanId: action === "downgrade" ? plan.id : null,
      scheduledBillingPeriod: action === "downgrade" ? billingPeriod : null
    });

    return {
      success: true,
      data: null,
      message: isUpgrade
        ? "Subscription updated successfully."
        : "Downgrade scheduled for the end of the current billing cycle."
    };
  } catch (error: any) {
    console.error("[Stripe Change Plan Error]:", error);
    return {
      success: false,
      code: "PAYMENT_PROVIDER_ERROR",
      message:
        error.message ||
        "Failed to process the plan change with the payment provider."
    };
  }
}

export async function createPlansService(
  data: Plan
): Promise<ServiceResult<Plan>> {
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
      []) as unknown as BillingOptionType[];
    if (billingOptions.length === 0) {
      return {
        success: false,
        code: "UNPROCESSABLE_ENTITY",
        message: "At least one billing option must be provided."
      };
    }

    const basePrice = Number(data.price);
    const updatedBillingOptions: BillingOptionType[] = [];

    for (const option of billingOptions) {
      const finalPrice = Math.round(
        calculateDiscountedPrice(
          basePrice,
          option.months,
          option.discountPercent
        )
      );

      const stripeCreatedPrice = await stripeService.createPlan(
        stripeProductKey?.value,
        {
          name: `${data.name} - ${option.period}`,
          description: data.description || "",
          currency: data.currency,
          unitAmount: finalPrice,
          interval: "month",
          intervalCount: option.months
        }
      );

      updatedBillingOptions.push({
        ...option,
        stripePriceId: stripeCreatedPrice.id
      });
    }

    const insertedPlan = await plansRepo.createPlan({
      ...data,
      billingOptions: updatedBillingOptions as any,
      paymentProviderProductId: stripeProductKey.value,
      paymentProviderPlanId: updatedBillingOptions[0].stripePriceId
    });

    return { success: true, data: insertedPlan };
  } catch (err: any) {
    console.error(err);
    return {
      success: false,
      code: "UNPROCESSABLE_ENTITY",
      message: err.message || err.error || "Unprocessable Entity"
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

  if (data.billingOptions || data.price) {
    const stripeProductKey = (await getAppConfig(
      configKeys.stripeAppConfigKey
    )) as AppConfig;
    const basePrice = Number(data.price || existingPlan.price);
    const incomingOptions = (data.billingOptions ||
      existingPlan.billingOptions) as unknown as BillingOptionType[];
    const existingOptions =
      (existingPlan.billingOptions as unknown as BillingOptionType[]) || [];
    const updatedBillingOptions: BillingOptionType[] = [];

    for (const option of incomingOptions) {
      const finalPrice = Math.round(
        calculateDiscountedPrice(
          basePrice,
          option.months,
          option.discountPercent
        )
      );

      const oldOption = existingOptions.find((o) => o.period === option.period);
      const oldRawTotal = Number(existingPlan.price) * (oldOption?.months || 1);
      const oldFinalPrice = Math.round(
        oldRawTotal - oldRawTotal * ((oldOption?.discountPercent || 0) / 100)
      );

      let stripePriceId = option.stripePriceId || oldOption?.stripePriceId;

      if (!stripePriceId || finalPrice !== oldFinalPrice) {
        const stripeCreatedPrice = await stripeService.createPlan(
          existingPlan.paymentProviderProductId || stripeProductKey?.value,
          {
            name: `${data.name || existingPlan.name} - ${option.period}`,
            description: data.description || existingPlan.description || "",
            currency: data.currency || existingPlan.currency,
            unitAmount: finalPrice,
            interval: "month",
            intervalCount: option.months
          }
        );
        stripePriceId = stripeCreatedPrice.id;
      }

      updatedBillingOptions.push({
        ...option,
        stripePriceId
      });
    }

    data.billingOptions = updatedBillingOptions as any;

    if (updatedBillingOptions.length > 0) {
      data.paymentProviderPlanId = updatedBillingOptions[0].stripePriceId;
    }
  }

  const plan = await plansRepo.updatePlan(id, data);
  return { success: true, data: plan };
}
