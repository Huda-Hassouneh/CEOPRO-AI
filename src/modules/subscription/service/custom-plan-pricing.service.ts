import { Prisma } from "../../../generated/prisma/client.js";

export type PricingFeatureInput = {
  featureId: string;
  estimatedUsage: number | string | Prisma.Decimal;
};

export type PricingVendorRate = {
  id: string;
  featureId: string | null;
  vendor: string;
  service: string;
  billingUnit: string;
  unitCost: number | string | Prisma.Decimal;
  currency: string;
  operationalMultiplier: number | string | Prisma.Decimal;
  variabilityReserve: number | string | Prisma.Decimal;
  verificationStatus: "confirmed" | "estimated" | "unconfirmed" | "deprecated";
  source?: string | null;
};

export type CustomPlanPricingInput = {
  quoteCurrency: string;
  features: PricingFeatureInput[];
  vendorRates: PricingVendorRate[];
  monthlyInfrastructureCost: number | string | Prisma.Decimal;
  activePayingTenants: number;
  estimatedOtherCost: number | string | Prisma.Decimal;
  targetGrossMargin: number | string | Prisma.Decimal;

  /**
   * The PDF defines vendor-cost/revenue as a separate, optional pre-sale floor
   * and a useful post-sale monitoring ratio. Automated self-service pricing
   * does NOT enforce it unless this flag is explicitly enabled by policy.
   */
  maxVendorCostRevenueRatio?: number | string | Prisma.Decimal | null;
  enforceVendorCostRatioFloor?: boolean;

  /** Commercial amount added after the cost-protecting floor. */
  fixedPlatformFee?: number | string | Prisma.Decimal;

  /** Round the final automated selling price UP to this increment (e.g. 1 or 5). */
  roundingIncrement?: number | string | Prisma.Decimal;

  /**
   * Features known to require a vendor rate. When omitted, legacy behavior is
   * preserved and every feature with positive estimated usage requires a rate.
   */
  vendorCostRequiredFeatureIds?: string[];

  fxRate?: number | string | Prisma.Decimal | null;
  fxSourceCurrency?: string | null;
  fxTargetCurrency?: string | null;
};

type DecimalInput = ConstructorParameters<typeof Prisma.Decimal>[0];

const D = (value: DecimalInput) => new Prisma.Decimal(value);
const ZERO = D(0);
const ONE = D(1);
const money = (value: Prisma.Decimal) =>
  value.toDecimalPlaces(2, Prisma.Decimal.ROUND_HALF_UP);

function assertGrossMargin(value: Prisma.Decimal) {
  if (value.lessThan(0) || value.greaterThanOrEqualTo(1)) {
    throw new Error("Invalid targetGrossMargin");
  }
}

function assertVendorCostRatio(value: Prisma.Decimal) {
  if (value.lessThanOrEqualTo(0) || value.greaterThan(1)) {
    throw new Error("Invalid maxVendorCostRevenueRatio");
  }
}

function roundUpToIncrement(value: Prisma.Decimal, increment: Prisma.Decimal) {
  if (increment.lessThanOrEqualTo(0)) return money(value);
  return value
    .div(increment)
    .ceil()
    .mul(increment)
    .toDecimalPlaces(2, Prisma.Decimal.ROUND_HALF_UP);
}

function convertRateToQuoteCurrency(
  rate: PricingVendorRate,
  input: CustomPlanPricingInput,
): Prisma.Decimal {
  const unitCost = D(rate.unitCost);
  if (rate.currency === input.quoteCurrency) return unitCost;

  if (
    input.fxRate == null ||
    input.fxSourceCurrency !== rate.currency ||
    input.fxTargetCurrency !== input.quoteCurrency
  ) {
    throw new Error(
      `Missing FX rate for ${rate.currency} -> ${input.quoteCurrency} (${rate.vendor}/${rate.service})`,
    );
  }

  return unitCost.mul(D(input.fxRate));
}

export function calculateCustomPlanPrice(input: CustomPlanPricingInput) {
  if (
    !Number.isInteger(input.activePayingTenants) ||
    input.activePayingTenants <= 0
  ) {
    throw new Error("activePayingTenants must be a positive integer");
  }

  const targetGrossMargin = D(input.targetGrossMargin);
  assertGrossMargin(targetGrossMargin);

  const enforceVendorCostRatioFloor =
    input.enforceVendorCostRatioFloor === true;
  const maxVendorCostRevenueRatio =
    input.maxVendorCostRevenueRatio == null
      ? null
      : D(input.maxVendorCostRevenueRatio);
  if (maxVendorCostRevenueRatio) {
    assertVendorCostRatio(maxVendorCostRevenueRatio);
  }
  if (enforceVendorCostRatioFloor && !maxVendorCostRevenueRatio) {
    throw new Error(
      "maxVendorCostRevenueRatio is required when vendor-cost floor enforcement is enabled",
    );
  }

  const fixedPlatformFee = D(input.fixedPlatformFee ?? 0);
  const roundingIncrement = D(input.roundingIncrement ?? 0);
  if (fixedPlatformFee.lessThan(0) || roundingIncrement.lessThan(0)) {
    throw new Error("Pricing policy amounts cannot be negative");
  }

  const featureUsage = new Map(
    input.features.map((feature) => [
      feature.featureId,
      D(feature.estimatedUsage),
    ]),
  );
  for (const [featureId, usage] of featureUsage) {
    if (usage.lessThan(0)) {
      throw new Error(`Estimated usage cannot be negative (${featureId})`);
    }
  }

  const pricedFeatureIds = new Set(
    input.vendorRates
      .filter(
        (rate) => rate.featureId && rate.verificationStatus !== "deprecated",
      )
      .map((rate) => rate.featureId as string),
  );

  const explicitlyRequired = input.vendorCostRequiredFeatureIds
    ? new Set(input.vendorCostRequiredFeatureIds)
    : null;
  const missingRateFeatureIds = [...featureUsage.entries()]
    .filter(([, usage]) => usage.greaterThan(0))
    .map(([featureId]) => featureId)
    .filter((featureId) =>
      explicitlyRequired ? explicitlyRequired.has(featureId) : true,
    )
    .filter((featureId) => !pricedFeatureIds.has(featureId));
  if (missingRateFeatureIds.length) {
    throw new Error(
      `Missing vendor rate for feature(s): ${missingRateFeatureIds.join(", ")}`,
    );
  }

  const vendorBreakdown: Array<{
    rateId: string;
    featureId: string;
    vendor: string;
    service: string;
    billingUnit: string;
    verificationStatus: PricingVendorRate["verificationStatus"];
    source?: string | null;
    estimatedUsage: string;
    normalizedUnitCost: string;
    operationalMultiplier: string;
    variabilityReserve: string;
    cost: string;
  }> = [];

  let estimatedVendorCost = ZERO;
  for (const rate of input.vendorRates) {
    if (!rate.featureId || rate.verificationStatus === "deprecated") continue;
    const usage = featureUsage.get(rate.featureId);
    if (!usage || usage.lessThanOrEqualTo(0)) continue;

    const normalizedUnitCost = convertRateToQuoteCurrency(rate, input);
    const operationalMultiplier = D(rate.operationalMultiplier);
    const variabilityReserve = D(rate.variabilityReserve);
    if (
      operationalMultiplier.lessThanOrEqualTo(0) ||
      variabilityReserve.lessThan(1)
    ) {
      throw new Error(`Invalid multiplier on vendor rate ${rate.id}`);
    }

    const cost = usage
      .mul(normalizedUnitCost)
      .mul(operationalMultiplier)
      .mul(variabilityReserve);
    estimatedVendorCost = estimatedVendorCost.add(cost);

    vendorBreakdown.push({
      rateId: rate.id,
      featureId: rate.featureId,
      vendor: rate.vendor,
      service: rate.service,
      billingUnit: rate.billingUnit,
      verificationStatus: rate.verificationStatus,
      source: rate.source,
      estimatedUsage: usage.toString(),
      normalizedUnitCost: normalizedUnitCost.toString(),
      operationalMultiplier: operationalMultiplier.toString(),
      variabilityReserve: variabilityReserve.toString(),
      cost: money(cost).toString(),
    });
  }

  const monthlyInfrastructureCost = D(input.monthlyInfrastructureCost);
  const estimatedOtherCost = D(input.estimatedOtherCost);
  if (monthlyInfrastructureCost.lessThan(0) || estimatedOtherCost.lessThan(0)) {
    throw new Error("Cost inputs cannot be negative");
  }

  const estimatedInfrastructureCost = monthlyInfrastructureCost.div(
    input.activePayingTenants,
  );
  const estimatedTotalCost = estimatedVendorCost
    .add(estimatedInfrastructureCost)
    .add(estimatedOtherCost);

  // Gross margin is not markup: cost / (1 - target margin).
  const grossMarginFloor = estimatedTotalCost.div(ONE.sub(targetGrossMargin));

  // Kept separately for PDF compatibility, risk monitoring and optional policy.
  const vendorCostRatioFloor = maxVendorCostRevenueRatio
    ? estimatedVendorCost.div(maxVendorCostRevenueRatio)
    : ZERO;

  const minimumSafePrice =
    enforceVendorCostRatioFloor &&
    vendorCostRatioFloor.greaterThan(grossMarginFloor)
      ? vendorCostRatioFloor
      : grossMarginFloor;

  const recommendedPriceBeforeRounding = minimumSafePrice.add(fixedPlatformFee);
  const recommendedPrice = roundUpToIncrement(
    recommendedPriceBeforeRounding,
    roundingIncrement,
  );

  const warnings = vendorBreakdown
    .filter((item) => item.verificationStatus !== "confirmed")
    .map(
      (item) =>
        `${item.vendor}/${item.service} rate is ${item.verificationStatus}`,
    );

  return {
    estimatedVendorCost: money(estimatedVendorCost),
    estimatedInfrastructureCost: money(estimatedInfrastructureCost),
    estimatedOtherCost: money(estimatedOtherCost),
    estimatedTotalCost: money(estimatedTotalCost),
    grossMarginFloor: money(grossMarginFloor),
    vendorCostRatioFloor: money(vendorCostRatioFloor),
    minimumSafePrice: money(minimumSafePrice),
    fixedPlatformFee: money(fixedPlatformFee),
    recommendedPriceBeforeRounding: money(recommendedPriceBeforeRounding),
    recommendedPrice,
    targetGrossMargin,
    maxVendorCostRevenueRatio,
    enforceVendorCostRatioFloor,
    vendorBreakdown,
    warnings,
  };
}

export function calculateExpectedProfitability(
  finalPriceInput: number | string | Prisma.Decimal,
  estimatedTotalCostInput: number | string | Prisma.Decimal,
  estimatedVendorCostInput: number | string | Prisma.Decimal,
) {
  const finalPrice = D(finalPriceInput);
  if (finalPrice.lessThanOrEqualTo(0)) {
    throw new Error("finalPrice must be greater than zero");
  }
  const estimatedTotalCost = D(estimatedTotalCostInput);
  const estimatedVendorCost = D(estimatedVendorCostInput);

  return {
    expectedGrossMargin: ONE.sub(estimatedTotalCost.div(finalPrice)),
    expectedVendorCostRatio: estimatedVendorCost.div(finalPrice),
  };
}
