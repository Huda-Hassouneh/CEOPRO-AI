import { z } from "zod";

const currencySchema = z
  .string()
  .length(3)
  .regex(/^[A-Z]{3}$/);

const moneySchema = z.number().nonnegative().max(99999999.99);

const ratioSchema = z.number().min(0).max(0.999999);

const maxCostRatioSchema = z.number().positive().max(1);

const billingOptionSchema = z.object({
  period: z.string().min(1).max(50),
  months: z.number().int().positive().max(120),
  discountPercent: z.number().min(0).max(100).default(0),
});

export const customPlanQuoteFeatureSchema = z.object({
  featureId: z.uuid(),
  limitValue: z.number().int().nonnegative().nullable().optional(),
  estimatedUsage: z.number().nonnegative().default(0),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

const quoteFields = {
  name: z.string().trim().min(1).max(50),
  name_ar: z.string().trim().min(1).max(50),

  description: z.string().trim().max(4000).optional(),
  description_ar: z.string().trim().max(4000).optional(),

  currency: currencySchema.default("JOD"),

  billingIntervalValue: z.number().int().positive().default(1),

  billingIntervalUnit: z
    .enum(["day", "week", "month", "year"])
    .default("month"),

  trialPeriodValue: z.number().int().nonnegative().max(365).default(0),

  billingOptions: z
    .array(billingOptionSchema)
    .min(1)
    .default([
      {
        period: "monthly",
        months: 1,
        discountPercent: 0,
      },
    ]),

  features: z.array(customPlanQuoteFeatureSchema).min(1),

  monthlyInfrastructureCost: moneySchema.default(0),

  activePayingTenants: z.number().int().positive().default(1),

  estimatedOtherCost: moneySchema.default(0),

  targetGrossMargin: ratioSchema.default(0.2),

  maxVendorCostRevenueRatio: maxCostRatioSchema.default(0.2),

  fxRate: z.number().positive().optional(),

  fxSourceCurrency: currencySchema.optional(),

  fxTargetCurrency: currencySchema.optional(),

  fxSource: z.string().trim().max(255).optional(),

  fxRateAt: z.iso.datetime().optional(),

  expiresAt: z.iso.datetime().optional(),
};

export const createCustomPlanQuoteSchema = z.object(quoteFields).strict();

export const updateCustomPlanQuoteSchema = z
  .object({
    name: quoteFields.name.optional(),

    name_ar: quoteFields.name_ar.optional(),

    description: quoteFields.description,

    description_ar: quoteFields.description_ar,

    currency: currencySchema.optional(),

    billingIntervalValue: quoteFields.billingIntervalValue.optional(),

    billingIntervalUnit: quoteFields.billingIntervalUnit.optional(),

    trialPeriodValue: quoteFields.trialPeriodValue.optional(),

    billingOptions: z.array(billingOptionSchema).min(1).optional(),

    features: z.array(customPlanQuoteFeatureSchema).min(1).optional(),

    monthlyInfrastructureCost: moneySchema.optional(),

    activePayingTenants: z.number().int().positive().optional(),

    estimatedOtherCost: moneySchema.optional(),

    targetGrossMargin: ratioSchema.optional(),

    maxVendorCostRevenueRatio: maxCostRatioSchema.optional(),

    fxRate: z.number().positive().nullable().optional(),

    fxSourceCurrency: currencySchema.nullable().optional(),

    fxTargetCurrency: currencySchema.nullable().optional(),

    fxSource: z.string().trim().max(255).nullable().optional(),

    fxRateAt: z.iso.datetime().nullable().optional(),

    expiresAt: z.iso.datetime().nullable().optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, {
    message: "At least one field is required",
  });

export const customPlanQuoteIdParamsSchema = z.object({
  id: z.uuid(),
});

export const approveCustomPlanQuoteSchema = z
  .object({
    finalPrice: moneySchema.positive(),

    overrideReason: z.string().trim().min(10).max(2000).optional(),
  })
  .strict();

/**
 * IMPORTANT:
 *
 * Keep the raw vendor-rate object schema separate
 * from cross-field refinements.
 *
 * Zod v4 does NOT allow:
 *
 * refinedSchema.partial()
 *
 * so updateVendorRateSchema must be created from
 * vendorRateBaseSchema.partial() instead.
 */
const vendorRateBaseSchema = z
  .object({
    featureId: z.uuid().nullable().optional(),

    vendor: z.string().trim().min(1).max(100),

    service: z.string().trim().min(1).max(150),

    billingUnit: z.string().trim().min(1).max(80),

    unitCost: z.number().nonnegative(),

    currency: currencySchema,

    operationalMultiplier: z.number().positive().default(1),

    variabilityReserve: z.number().min(1).default(1),

    effectiveFrom: z.iso.datetime().optional(),

    effectiveTo: z.iso.datetime().nullable().optional(),

    verificationStatus: z
      .enum(["confirmed", "estimated", "unconfirmed", "deprecated"])
      .default("unconfirmed"),

    source: z.string().trim().max(4000).optional(),

    metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

type VendorRateDateFields = {
  effectiveFrom?: string;
  effectiveTo?: string | null;
};

/**
 * Reusable cross-field validation.
 *
 * For update requests we can only compare dates when
 * BOTH are provided in the same request.
 *
 * Validation involving an existing DB value should be
 * handled in the service layer after loading the record.
 */
function hasValidVendorRateDates(value: VendorRateDateFields): boolean {
  if (!value.effectiveFrom || !value.effectiveTo) {
    return true;
  }

  return new Date(value.effectiveTo) > new Date(value.effectiveFrom);
}

/**
 * CREATE
 *
 * Apply refinement AFTER the object schema has been built.
 */
export const vendorRateSchema = vendorRateBaseSchema.refine(
  hasValidVendorRateDates,
  {
    message: "effectiveTo must be later than effectiveFrom",
    path: ["effectiveTo"],
  },
);

/**
 * UPDATE
 *
 * IMPORTANT:
 *
 * .partial() is called on the UNREFINED base schema.
 * Refinements are applied afterwards.
 *
 * This fixes:
 *
 * Error:
 * .partial() cannot be used on object schemas
 * containing refinements
 */
export const updateVendorRateSchema = vendorRateBaseSchema
  .partial()
  .refine((value) => Object.keys(value).length > 0, {
    message: "At least one field is required",
  })
  .refine(hasValidVendorRateDates, {
    message: "effectiveTo must be later than effectiveFrom",
    path: ["effectiveTo"],
  });

export const vendorRateIdParamsSchema = z.object({
  id: z.uuid(),
});

const customPlanSelectionFeatureSchema = z
  .object({
    featureId: z.uuid(),
    limitValue: z.number().int().nonnegative().nullable().optional(),
  })
  .strict();

export const customPlanPreviewSchema = z
  .object({
    features: z.array(customPlanSelectionFeatureSchema).min(1).max(100),
    billingPeriod: z.string().trim().min(1).max(50).default("monthly"),
  })
  .strict();

export const customPlanManualReviewSchema = customPlanPreviewSchema
  .extend({
    requestId: z.uuid(),
  })
  .strict();

export const customPlanInstantCheckoutSchema = customPlanPreviewSchema
  .extend({
    requestId: z.uuid(),
    paymentMethod: z
      .enum(["card", "stripe", "googlePay", "paypal"])
      .default("stripe"),
    promoCode: z.string().trim().min(1).max(50).optional(),
  })
  .strict();

const automaticFeatureLimitSchema = z
  .object({
    min: z.number().int().nonnegative().optional(),
    max: z.number().int().positive().optional(),
    step: z.number().int().positive().optional(),
  })
  .strict()
  .refine(
    (value) => value.min == null || value.max == null || value.min <= value.max,
    {
      message: "Feature minimum cannot exceed maximum",
    },
  );

export const customPlanPricingPolicyUpdateSchema = z
  .object({
    currency: currencySchema.optional(),
    targetGrossMargin: ratioSchema.optional(),
    fixedPlatformFee: moneySchema.optional(),
    monthlyInfrastructureCost: moneySchema.optional(),
    activePayingTenants: z.number().int().positive().optional(),
    estimatedOtherCost: moneySchema.optional(),
    roundingIncrement: z.number().nonnegative().max(10000).optional(),
    maxAutomaticMonthlyPrice: moneySchema.positive().optional(),
    maxAutomaticQuotaPerFeature: z.number().int().positive().optional(),
    enforceVendorCostRatioFloor: z.boolean().optional(),
    maxVendorCostRevenueRatio: maxCostRatioSchema.optional(),
    fxRate: z.number().positive().nullable().optional(),
    fxSourceCurrency: currencySchema.nullable().optional(),
    fxTargetCurrency: currencySchema.nullable().optional(),
    fxSource: z.string().trim().max(255).nullable().optional(),
    fxRateAt: z.iso.datetime().nullable().optional(),
    trialPeriodValue: z.number().int().nonnegative().max(365).optional(),
    billingOptions: z.array(billingOptionSchema).min(1).max(12).optional(),
    featureLimits: z.record(z.string(), automaticFeatureLimitSchema).optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, {
    message: "At least one pricing policy field is required",
  });

export type CreateCustomPlanQuoteInput = z.infer<
  typeof createCustomPlanQuoteSchema
>;

export type UpdateCustomPlanQuoteInput = z.infer<
  typeof updateCustomPlanQuoteSchema
>;

export type ApproveCustomPlanQuoteInput = z.infer<
  typeof approveCustomPlanQuoteSchema
>;

export type VendorRateInput = z.infer<typeof vendorRateSchema>;

export type CustomPlanPreviewInput = z.infer<typeof customPlanPreviewSchema>;
export type CustomPlanManualReviewInput = z.infer<
  typeof customPlanManualReviewSchema
>;
export type CustomPlanInstantCheckoutInput = z.infer<
  typeof customPlanInstantCheckoutSchema
>;
export type CustomPlanPricingPolicyUpdateInput = z.infer<
  typeof customPlanPricingPolicyUpdateSchema
>;
