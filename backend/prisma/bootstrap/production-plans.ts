import "dotenv/config";
import { prisma } from "../../src/config/database.js";
import {
  assertSafeEnvironment,
  displayDatabaseTarget
} from "./helpers/environment.js";
import { stableHash } from "./helpers/hash.js";
import { assertManifest, ensureManifestFeatures } from "./helpers/manifest.js";
import { info, line, logStep, success } from "./helpers/logs.js";
import {
  getSharedStripeProductId,
  reconcileStripePrices,
  retireReplacedStripePrices
} from "./helpers/stripe.js";
import {
  optionPrice,
  validatePlanOptions
} from "../../src/modules/subscription/service/plan-pricing.js";
import {
  PRODUCTION_PLAN_CATALOG_VERSION,
  PRODUCTION_PLAN_NAMES,
  PRODUCTION_PLANS,
  type ProductionPlanDefinition
} from "../../src/config/production-plans.js";
const args = new Set(process.argv.slice(2));
const DRY_RUN = args.has("--dry-run");
const VERIFY_ONLY = args.has("--verify-only");
const RETIRE_UNKNOWN = !args.has("--keep-other-standard-plans");
const ALLOW_ACTIVE_ENTITLEMENT_CHANGES =
  process.env.ALLOW_ACTIVE_STANDARD_PLAN_ENTITLEMENT_CHANGES === "true";
function fail(message: string): never {
  throw new Error(message);
}
function desiredFeatureSignature(plan: ProductionPlanDefinition) {
  return plan.features
    .map((feature) => ({
      code: feature.code,
      limitValue: feature.limitValue,
      metadata: feature.metadata ?? null
    }))
    .sort((a, b) => a.code.localeCompare(b.code));
}
function currentFeatureSignature(plan: any) {
  return (plan.planFeatures ?? [])
    .map((row: any) => ({
      code: row.feature.code,
      limitValue: row.limit_value,
      metadata: row.metadata ?? null
    }))
    .sort((a: any, b: any) => a.code.localeCompare(b.code));
}
function entitlementSignatureChanged(
  plan: any,
  desired: ProductionPlanDefinition
) {
  return (
    stableHash(currentFeatureSignature(plan)) !==
    stableHash(desiredFeatureSignature(desired))
  );
}
async function reconcilePlan(
  plan: ProductionPlanDefinition,
  productId: string
) {
  logStep(`Reconciling ${plan.name}`);
  const matches = await prisma.plan.findMany({
    where: {
      name: plan.name,
      planType: "standard",
      tenantId: null
    },
    include: {
      planFeatures: { include: { feature: true } },
      activeSubscriptions: {
        where: {
          status: {
            in: [
              "active",
              "trialing",
              "past_due",
              "pending",
              "payment_failed",
              "paused"
            ]
          }
        },
        select: { id: true }
      }
    }
  });
  if (matches.length > 1) {
    fail(
      `Multiple tenant-neutral standard plans named '${plan.name}' exist. Resolve duplicates before bootstrap.`
    );
  }
  const existing = matches[0] ?? null;
  if (
    existing &&
    entitlementSignatureChanged(existing, plan) &&
    existing.activeSubscriptions.length > 0 &&
    !ALLOW_ACTIVE_ENTITLEMENT_CHANGES
  ) {
    fail(
      `${plan.name} has ${existing.activeSubscriptions.length} current subscription(s) and its feature entitlements differ from the manifest. Refusing to mutate active customer entitlements. Create a new catalog version/tier or set ALLOW_ACTIVE_STANDARD_PLAN_ENTITLEMENT_CHANGES=true only after deliberate review.`
    );
  }
  if (VERIFY_ONLY && !existing) {
    fail(`${plan.name} is missing from the database.`);
  }
  const stripe = await reconcileStripePrices(plan, existing, productId, {
    dryRun: DRY_RUN,
    verifyOnly: VERIFY_ONLY
  });
  if (DRY_RUN) {
    info(
      existing
        ? `would reconcile DB plan ${existing.id}`
        : "would create DB plan"
    );
    return;
  }
  if (VERIFY_ONLY) {
    const desiredFeatures = desiredFeatureSignature(plan);
    const actualFeatures = currentFeatureSignature(existing);
    if (stableHash(desiredFeatures) !== stableHash(actualFeatures)) {
      fail(
        `${plan.name} feature entitlements do not match the production manifest.`
      );
    }
    if (
      Number(existing.price) !== plan.price ||
      existing.currency !== plan.currency ||
      existing.billingIntervalValue !== plan.billingIntervalValue ||
      existing.billingIntervalUnit !== plan.billingIntervalUnit ||
      existing.tierLevel !== plan.tierLevel ||
      existing.trialPeriodValue !== plan.trialPeriodValue ||
      existing.paymentProviderProductId !== productId ||
      existing.paymentProviderPlanId !==
        stripe.options.find((option) => option.period === "monthly")
          ?.stripePriceId ||
      !existing.isActive
    ) {
      fail(
        `${plan.name} database fields do not match the production manifest.`
      );
    }
    success(`${plan.name} DB + Stripe configuration verified`);
    return;
  }
  const featureRows = await prisma.feature.findMany({
    where: { code: { in: plan.features.map((feature) => feature.code) } },
    select: { id: true, code: true }
  });
  const featureIdByCode = new Map(
    featureRows.map((row: any) => [row.code, row.id])
  );
  for (const entitlement of plan.features) {
    if (!featureIdByCode.has(entitlement.code)) {
      fail(`Feature '${entitlement.code}' disappeared during bootstrap.`);
    }
  }
  const billingOptions = stripe.options;
  const monthlyPrice = billingOptions.find(
    (option) => option.period === "monthly"
  )?.stripePriceId;
  if (!monthlyPrice) fail(`${plan.name} monthly Stripe Price is missing.`);
  const persisted = await prisma.$transaction(async (tx) => {
    const planRow = existing
      ? await tx.plan.update({
          where: { id: existing.id },
          data: {
            name: plan.name,
            name_ar: plan.name_ar,
            tierLevel: plan.tierLevel,
            planType: "standard",
            tenantId: null,
            description: plan.description,
            description_ar: plan.description_ar,
            price: plan.price,
            currency: plan.currency,
            billingIntervalValue: plan.billingIntervalValue,
            billingIntervalUnit: plan.billingIntervalUnit,
            trialPeriodValue: plan.trialPeriodValue,
            paymentProviderProductId: productId,
            paymentProviderPlanId: monthlyPrice,
            billingOptions,
            isActive: true
          }
        })
      : await tx.plan.create({
          data: {
            name: plan.name,
            name_ar: plan.name_ar,
            tierLevel: plan.tierLevel,
            planType: "standard",
            tenantId: null,
            description: plan.description,
            description_ar: plan.description_ar,
            price: plan.price,
            currency: plan.currency,
            billingIntervalValue: plan.billingIntervalValue,
            billingIntervalUnit: plan.billingIntervalUnit,
            trialPeriodValue: plan.trialPeriodValue,
            paymentProviderProductId: productId,
            paymentProviderPlanId: monthlyPrice,
            billingOptions,
            isActive: true
          }
        });
    for (const option of billingOptions) {
      const resolved = validatePlanOptions(
        [{ ...option, stripePriceId: undefined } as any],
        plan.price,
        plan.billingIntervalValue,
        plan.billingIntervalUnit,
        plan.currency
      )[0];
      const amount = optionPrice(
        plan.price,
        plan.billingIntervalValue,
        plan.billingIntervalUnit,
        resolved,
        plan.currency
      );
      const priceVersion = await tx.planPriceVersion.findUnique({
        where: { stripePriceId: option.stripePriceId }
      });
      if (priceVersion && priceVersion.planId !== planRow.id) {
        fail(
          `Stripe Price ${option.stripePriceId} is already mapped to another CEOPRO plan.`
        );
      }
      await tx.planPriceVersion.upsert({
        where: { stripePriceId: option.stripePriceId },
        create: {
          planId: planRow.id,
          stripePriceId: option.stripePriceId,
          periodCode: option.period,
          intervalUnit: option.intervalUnit,
          intervalCount: option.intervalCount,
          amount,
          currency: plan.currency,
          retiredAt: null
        },
        update: {
          periodCode: option.period,
          intervalUnit: option.intervalUnit,
          intervalCount: option.intervalCount,
          amount,
          currency: plan.currency,
          retiredAt: null
        }
      });
    }
    await tx.planPriceVersion.updateMany({
      where: {
        planId: planRow.id,
        stripePriceId: { notIn: stripe.newPriceIds },
        retiredAt: null
      },
      data: { retiredAt: new Date() }
    });
    await tx.planFeature.deleteMany({ where: { plan_id: planRow.id } });
    await tx.planFeature.createMany({
      data: plan.features.map((entitlement) => ({
        plan_id: planRow.id,
        feature_id: featureIdByCode.get(entitlement.code)!,
        limit_value: entitlement.limitValue,
        metadata: (entitlement.metadata ?? undefined) as any
      }))
    });
    return planRow;
  });
  await retireReplacedStripePrices({
    planName: plan.name,
    oldPriceIds: stripe.oldPriceIds,
    newPriceIds: stripe.newPriceIds
  });
  success(`${plan.name} persisted as plan ${persisted.id}`);
}
async function retireUnknownStandardPlans() {
  if (!RETIRE_UNKNOWN) {
    info(
      "keeping non-manifest standard plans because --keep-other-standard-plans was supplied"
    );
    return;
  }
  const unknown = await prisma.plan.findMany({
    where: {
      planType: "standard",
      tenantId: null,
      name: { notIn: [...PRODUCTION_PLAN_NAMES] },
      isActive: true
    },
    select: { id: true, name: true }
  });
  if (!unknown.length) {
    success("no unknown active standard plans remain in the public catalog");
    return;
  }
  if (VERIFY_ONLY) {
    fail(
      `Unexpected active standard plan(s): ${unknown.map((plan: any) => plan.name).join(", ")}.`
    );
  }
  if (DRY_RUN) {
    for (const plan of unknown as any[])
      info(`would deactivate non-manifest plan ${plan.name}`);
    return;
  }
  await prisma.plan.updateMany({
    where: { id: { in: unknown.map((plan: any) => plan.id) } },
    data: { isActive: false }
  });
  for (const plan of unknown as any[])
    success(`deactivated non-manifest catalog plan ${plan.name}`);
}
function billingOptionSignature(options: readonly any[]) {
  return options
    .map((option) => ({
      period: option.period,
      months: option.months ?? null,
      intervalUnit: option.intervalUnit ?? "month",
      intervalCount: option.intervalCount ?? option.months,
      discountPercent: option.discountPercent
    }))
    .sort((a, b) => String(a.period).localeCompare(String(b.period)));
}
async function verifyFinalState() {
  logStep("Final production catalog verification");
  const active = await prisma.plan.findMany({
    where: { planType: "standard", tenantId: null, isActive: true },
    include: { planFeatures: { include: { feature: true } } },
    orderBy: { tierLevel: "asc" }
  });
  if (RETIRE_UNKNOWN && active.length !== PRODUCTION_PLANS.length) {
    fail(
      `Expected ${PRODUCTION_PLANS.length} active production plans, found ${active.length}: ${active.map((plan: any) => plan.name).join(", ")}.`
    );
  }
  for (const desired of PRODUCTION_PLANS) {
    const actual = active.find((plan: any) => plan.name === desired.name);
    if (!actual) fail(`Missing active production plan ${desired.name}.`);
    if (entitlementSignatureChanged(actual, desired)) {
      fail(`${desired.name} final feature set does not match the manifest.`);
    }
    const options = actual.billingOptions as any[];
    if (
      stableHash(billingOptionSignature(options)) !==
      stableHash(billingOptionSignature(desired.billingOptions))
    ) {
      fail(`${desired.name} final billing options do not match the manifest.`);
    }
    success(
      `${desired.name}: ${Number(actual.price).toFixed(2)} ${actual.currency}/month, ${actual.planFeatures.length} entitlements, ${options.length} billing options`
    );
  }
}
async function main() {
  assertSafeEnvironment({ dryRun: DRY_RUN, verifyOnly: VERIFY_ONLY });
  assertManifest();
  console.log("");
  line();
  console.log(" CEOPRO Production Standard-Plan Bootstrap");
  line();
  console.log(`Catalog version : ${PRODUCTION_PLAN_CATALOG_VERSION}`);
  console.log(
    `Mode            : ${VERIFY_ONLY ? "VERIFY ONLY" : DRY_RUN ? "DRY RUN" : "APPLY"}`
  );
  console.log(`Database        : ${displayDatabaseTarget()}`);
  console.log(`Plans           : ${PRODUCTION_PLAN_NAMES.join(" → ")}`);
  console.log(
    `Retire others   : ${RETIRE_UNKNOWN ? "yes (deactivate only, never delete)" : "no"}`
  );
  line();
  await ensureManifestFeatures({ dryRun: DRY_RUN, verifyOnly: VERIFY_ONLY });
  const productId = await getSharedStripeProductId({
    dryRun: DRY_RUN,
    verifyOnly: VERIFY_ONLY
  });
  for (const plan of PRODUCTION_PLANS) {
    await reconcilePlan(plan, productId);
  }
  await retireUnknownStandardPlans();
  if (!DRY_RUN) await verifyFinalState();
  console.log("");
  line();
  console.log(
    VERIFY_ONLY
      ? " Production catalog verification PASSED"
      : DRY_RUN
        ? " Dry run complete — no CEOPRO plan/feature rows or Stripe Prices were created/changed"
        : " Production catalog bootstrap COMPLETED"
  );
  line();
}
main()
  .catch((error) => {
    console.error("\nProduction plan bootstrap failed:");
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
