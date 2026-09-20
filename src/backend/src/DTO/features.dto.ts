import { z } from "zod";

const requiredString = (message: string) => z.string({ error: message });

const requiredUuid = (message: string) =>
  requiredString(message).uuid("Invalid ID format. Must be a valid UUID.");

const optionalPositiveInt = (label: string, max?: number) => {
  let schema = z.coerce
    .number()
    .int()
    .positive(`${label} must be a positive integer`);
  if (max !== undefined) {
    schema = schema.max(max, `${label} cannot exceed ${max}`);
  }
  return schema.optional();
};

const boundedString = (min: number, max: number, label: string) =>
  z
    .string()
    .min(min, `${label} must be at least ${min} characters`)
    .max(max, `${label} cannot exceed ${max} characters`);

const FeatureTypeEnum = z.enum(["boolean", "limit"], {
  error: "type is required and must be either 'boolean' or 'limit'"
});

const AggregationTypeEnum = z.enum(["sum", "max"], {
  error: "aggregation_type must be either 'sum' or 'max'"
});

const ResetCycleEnum = z.enum(["billing_period", "lifetime"], {
  error: "reset_cycle must be either 'billing_period' or 'lifetime'"
});

export const pricingQuerySchema = z.object({
  product_id: requiredUuid("product_id query parameter is required")
});

export const sentimentBatchQuerySchema = z.object({
  batch_size: optionalPositiveInt("batch_size")
});

export const subjectSummaryQuerySchema = z.object({
  subject_type: z.enum(["PRODUCT", "COMPETITOR", "BUSINESS"], {
    error: "subject_type must be one of 'PRODUCT', 'COMPETITOR', or 'BUSINESS'"
  }),
  subject_id: requiredUuid("subject_id query parameter is required")
});

export const ragQuerySchema = z.object({
  query_text: requiredString("query_text query parameter is required").min(
    1,
    "query_text cannot be empty"
  ),
  top_k: optionalPositiveInt("top_k", 20) // Defaults to 5 in the controller
});

export const extractionPendingQuerySchema = z.object({
  limit: optionalPositiveInt("limit")
});

const featureFields = {
  name: boundedString(2, 100, "name"),
  name_ar: boundedString(2, 100, "name_ar"),

  description: z.string().max(500, "description is too long").optional(),
  description_ar: z.string().max(500, "description_ar is too long").optional(),

  type: FeatureTypeEnum,

  unit: z.string().max(50, "unit cannot exceed 50 characters").optional(),
  unit_ar: z.string().max(50, "unit_ar cannot exceed 50 characters").optional(),

  aggregation_type: AggregationTypeEnum.optional(),
  reset_cycle: ResetCycleEnum.optional()
};

export const createFeatureSchema = z.object({
  code: requiredString("feature_code is required")
    .min(3, "feature_code must be at least 3 characters")
    .max(50, "feature_code cannot exceed 50 characters")
    .regex(
      /^[a-z0-9_]+$/,
      "feature_code must only contain lowercase letters, numbers, and underscores (e.g., ai_pricing)"
    ),
  ...featureFields
});

export const updateFeatureSchema = z
  .object({ ...featureFields })
  .partial()
  .strict();

export const featureIdParamSchema = z.object({
  id: requiredUuid("Invalid feature ID format. Must be a valid UUID.")
});

const billingOptionSchema = z.object({
  period: z.string().min(1, "Period code is required"),
  months: z.number().int().positive("Months must be a positive integer"),
  discountPercent: z
    .number()
    .min(0, "Discount cannot be negative")
    .max(100, "Discount cannot exceed 100%")
});

const planFeatureInputSchema = z.object({
  featureId: z.string().uuid("Invalid feature ID format"),
  limitValue: z.number().int().nullable().optional()
});

export const createPlanSchema = z.object({
  name: z
    .string()
    .min(1, "Plan name is required")
    .max(50, "Plan name cannot exceed 50 characters"),

  name_ar: z
    .string()
    .min(1, "Arabic plan name is required")
    .max(50, "Arabic plan name cannot exceed 50 characters"),

  tier_level: z
    .number()
    .int()
    .positive("Tier level must be a positive integer"),

  description: z.string().optional(),
  description_ar: z.string().optional(),

  price: z.number().positive("Price must be a positive number"),
  currency: z
    .string()
    .length(3, "Currency code must be exactly 3 characters")
    .default("usd"),
  billingIntervalValue: z
    .number()
    .int()
    .positive("Billing interval value must be at least 1"),
  billingIntervalUnit: z.string().min(1, "Billing interval unit is required"),
  trialPeriodValue: z
    .number()
    .int()
    .nonnegative("Trial days cannot be negative")
    .optional()
    .default(0),
  paymentProviderProductId: z.string().max(255).optional(),
  paymentProviderPlanId: z.string().max(255).optional(),
  isActive: z.boolean().optional().default(true),
  billingOptions: z.array(billingOptionSchema).optional(),
  features: z.array(planFeatureInputSchema).optional()
});

export const updatePlanSchema = createPlanSchema.partial();

export type CreatePlanInput = z.infer<typeof createPlanSchema>;
export type UpdatePlanInput = z.infer<typeof updatePlanSchema>;
