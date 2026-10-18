import { prisma } from "../../../src/config/database.js";
import { configKeys } from "../../../src/config/keys.config.js";
import {
  optionPrice,
  validatePlanOptions
} from "../../../src/modules/subscription/service/plan-pricing.js";
import { stripeService } from "../../../src/modules/subscription/client/payment-providers/stripe/stripe.client.js";
import { toStripeMinorUnits } from "../../../src/utils/currency.js";
import {
  PRODUCTION_PLAN_CATALOG_VERSION,
  type ProductionPlanDefinition
} from "../../../src/config/production-plans.js";
import { stableHash } from "./hash.js";
import { info, logStep, success, warn } from "./logs.js";
import type { BootstrapExecutionMode } from "./environment.js";
export async function getSharedStripeProductId(
  mode: BootstrapExecutionMode
): Promise<string> {
  logStep("Verifying shared CEOPRO Stripe Product");
  const config = await prisma.appConfig.findUnique({
    where: { key: configKeys.stripeAppConfigKey }
  });
  if (!config?.value) {
    throw new Error(
      "STRIPE_PRODUCT_ID is missing. Run 'npm run bootstrap:stripe' first (or 'npm run bootstrap:production')."
    );
  }
  const product = await stripeService.stripe.products.retrieve(config.value);
  if ((product as any).deleted) {
    throw new Error(`Configured Stripe Product ${config.value} was deleted.`);
  }
  if (!product.active) {
    if (mode.verifyOnly) {
      throw new Error(`Configured Stripe Product ${product.id} is inactive.`);
    }
    if (mode.dryRun) {
      info(`would reactivate Stripe Product ${product.id}`);
    } else {
      await stripeService.stripe.products.update(product.id, { active: true });
    }
  }
  success(`Stripe Product ${product.id}`);
  return product.id;
}
function priceMatches(
  stripePrice: any,
  productId: string,
  amount: number,
  currency: string,
  interval: string,
  intervalCount: number
): boolean {
  const priceProduct =
    typeof stripePrice.product === "string"
      ? stripePrice.product
      : stripePrice.product?.id;
  return (
    priceProduct === productId &&
    stripePrice.currency === currency.toLowerCase() &&
    stripePrice.unit_amount === toStripeMinorUnits(amount, currency) &&
    stripePrice.recurring?.interval === interval &&
    stripePrice.recurring?.interval_count === intervalCount
  );
}
function stripePriceIdempotencyKey(
  plan: ProductionPlanDefinition,
  option: any,
  amount: number,
  productId: string
): string {
  const fingerprint = stableHash({
    catalog: PRODUCTION_PLAN_CATALOG_VERSION,
    productId,
    plan: plan.code,
    period: option.period,
    amount,
    currency: plan.currency,
    intervalUnit: option.intervalUnit,
    intervalCount: option.intervalCount
  }).slice(0, 32);
  return `ceopro-prod-${plan.code}-${option.period}-${fingerprint}`;
}
export async function reconcileStripePrices(
  plan: ProductionPlanDefinition,
  existingPlan: any,
  productId: string,
  mode: BootstrapExecutionMode
) {
  const desiredOptions = validatePlanOptions(
    [...plan.billingOptions],
    plan.price,
    plan.billingIntervalValue,
    plan.billingIntervalUnit,
    plan.currency
  );
  const existingOptions = Array.isArray(existingPlan?.billingOptions)
    ? existingPlan.billingOptions
    : [];
  const oldPriceIds = existingOptions
    .map((option: any) => option?.stripePriceId)
    .filter(
      (value: unknown): value is string =>
        typeof value === "string" && value.length > 0
    );
  const reconciled: any[] = [];
  const newlyUsablePriceIds: string[] = [];
  for (const option of desiredOptions) {
    const amount = optionPrice(
      plan.price,
      plan.billingIntervalValue,
      plan.billingIntervalUnit,
      option,
      plan.currency
    );
    const previous = existingOptions.find(
      (candidate: any) => candidate?.period === option.period
    );
    let stripePriceId: string | null = previous?.stripePriceId ?? null;
    let stripePrice: any = null;
    if (stripePriceId) {
      try {
        stripePrice = await stripeService.stripe.prices.retrieve(stripePriceId);
      } catch {
        stripePrice = null;
      }
    }
    const matches =
      stripePrice &&
      priceMatches(
        stripePrice,
        productId,
        amount,
        plan.currency,
        option.intervalUnit,
        option.intervalCount
      );
    if (!matches) {
      if (mode.verifyOnly) {
        throw new Error(
          `${plan.name}/${option.period} does not have a matching Stripe Price.`
        );
      }
      if (mode.dryRun) {
        info(
          `would create/reconcile ${plan.name}/${option.period}: ${amount.toFixed(2)} ${plan.currency}`
        );
        reconciled.push({
          ...option,
          stripePriceId: stripePriceId ?? "dry-run-price"
        });
        continue;
      }
      const created = await stripeService.createPlan(productId, {
        name: `${plan.name} - ${option.period}`,
        description: plan.description,
        currency: plan.currency,
        unitAmount: amount,
        interval: option.intervalUnit,
        intervalCount: option.intervalCount,
        idempotencyKey: stripePriceIdempotencyKey(
          plan,
          option,
          amount,
          productId
        )
      });
      stripePriceId = created.id;
      stripePrice = created;
      newlyUsablePriceIds.push(created.id);
      success(
        `${plan.name}/${option.period}: Stripe Price ${created.id} (${amount.toFixed(2)} ${plan.currency})`
      );
    } else {
      success(
        `${plan.name}/${option.period}: reusing Stripe Price ${stripePriceId}`
      );
    }
    if (stripePrice && !stripePrice.active) {
      if (mode.verifyOnly) {
        throw new Error(
          `${plan.name}/${option.period} Stripe Price is inactive.`
        );
      }
      if (!mode.dryRun) {
        await stripeService.stripe.prices.update(stripePrice.id, {
          active: true
        });
        success(
          `${plan.name}/${option.period}: reactivated Stripe Price ${stripePrice.id}`
        );
      }
    }
    if (!mode.dryRun && !mode.verifyOnly && stripePriceId) {
      await stripeService.stripe.prices.update(stripePriceId, {
        nickname: `${plan.name} - ${option.period}`,
        metadata: {
          ceoproCatalogVersion: PRODUCTION_PLAN_CATALOG_VERSION,
          ceoproPlanCode: plan.code,
          ceoproPeriod: option.period,
          description: plan.description
        }
      });
    }
    reconciled.push({ ...option, stripePriceId });
  }
  return {
    options: reconciled,
    oldPriceIds,
    newPriceIds: reconciled
      .map((option) => option.stripePriceId)
      .filter((value): value is string => typeof value === "string"),
    newlyUsablePriceIds
  };
}
export async function retireReplacedStripePrices(args: {
  planName: string;
  oldPriceIds: string[];
  newPriceIds: string[];
}): Promise<void> {
  for (const oldPriceId of args.oldPriceIds) {
    if (args.newPriceIds.includes(oldPriceId)) continue;
    try {
      await stripeService.stripe.prices.update(oldPriceId, { active: false });
      success(`${args.planName}: retired replaced Stripe Price ${oldPriceId}`);
    } catch (error) {
      warn(
        `Could not archive replaced Stripe Price ${oldPriceId}; DB mapping is already safe:`,
        error
      );
    }
  }
}
export function assertSafeStripeBootstrapEnvironment() {
  const stripeKey = (process.env.STRIPE_SECRET_KEY || "").trim();
  if (!stripeKey) {
    throw new Error("STRIPE_SECRET_KEY is required for Stripe bootstrap.");
  }

  const liveConfirmed =
    process.env.CONFIRM_LIVE_STRIPE_BOOTSTRAP === "YES" ||
    process.env.CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP === "YES";
  if (stripeKey.startsWith("sk_live_") && !liveConfirmed) {
    throw new Error(
      "Refusing to create/use live Stripe catalog state without CONFIRM_LIVE_STRIPE_BOOTSTRAP=YES (or CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP=YES for the combined production-plan bootstrap)."
    );
  }

  const productionConfirmed =
    process.env.CONFIRM_PRODUCTION_STRIPE_BOOTSTRAP === "YES" ||
    process.env.CONFIRM_PRODUCTION_PLAN_BOOTSTRAP === "YES";
  if (process.env.NODE_ENV === "production" && !productionConfirmed) {
    throw new Error(
      "Refusing production Stripe bootstrap without CONFIRM_PRODUCTION_STRIPE_BOOTSTRAP=YES (or CONFIRM_PRODUCTION_PLAN_BOOTSTRAP=YES for the combined production-plan bootstrap)."
    );
  }
}
