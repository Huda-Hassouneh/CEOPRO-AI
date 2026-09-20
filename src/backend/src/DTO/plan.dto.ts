import { z } from "zod";

const intervalUnitSchema = z.enum(["day", "week", "month", "year"]);

const priceSchema = z
  .number()
  .nonnegative()
  .max(99999999.99, "Price cannot be greater than 99999999.99")
  .refine(
    (value) => Number.isInteger(value * 100),
    "Price must have at most 2 decimal places"
  );

const currencySchema = z
  .string()
  .length(3)
  .regex(/^[A-Z]{3}$/, "Currency must be a valid 3-letter uppercase code");

const trialPeriodSchema = z.object({
  trialPeriodValue: z.number().int().nonnegative().default(0)
});

const billingOptionSchema = z.object({
  period: z
    .string()
    .min(1, "Period name is required (e.g., 'monthly', 'three-months')"),
  months: z.number().int().positive("Months must be a positive integer"),
  discountPercent: z
    .number()
    .min(0, "Discount cannot be negative")
    .max(100, "Discount cannot exceed 100%")
    .default(0)
});

export const planSchema = z
  .object({
    name: z
      .string()
      .min(1, "Name is required")
      .max(50, "Name cannot exceed 50 characters"),
    name_ar: z
      .string()
      .min(1, "Arabic name is required")
      .max(50, "Arabic name cannot exceed 50 characters"),

    tierLevel: z
      .number()
      .int()
      .positive("Tier level must be a positive integer"),

    description: z.string().optional(),
    description_ar: z.string().optional(),
    price: priceSchema,
    currency: currencySchema,
    billingIntervalValue: z.number().int().positive(),
    billingIntervalUnit: intervalUnitSchema,
    isActive: z.boolean().default(true),

    billingOptions: z
      .array(billingOptionSchema)
      .min(1, "At least one billing option is required")
  })
  .and(trialPeriodSchema);

export const updatePlanSchema = z
  .object({
    name: z.string().min(1).max(50).optional(),
    name_ar: z.string().min(1).max(50).optional(),
    tierLevel: z.number().int().positive().optional(),
    description: z.string().optional(),
    description_ar: z.string().optional(),
    price: priceSchema.optional(),
    currency: currencySchema.optional(),
    billingIntervalValue: z.number().int().positive().optional(),
    billingIntervalUnit: intervalUnitSchema.optional(),
    trialPeriodValue: z.number().int().nonnegative().optional(),
    trialPeriodUnit: intervalUnitSchema.nullable().optional(),
    isActive: z.boolean().optional(),

    billingOptions: z
      .array(billingOptionSchema)
      .min(1, "At least one billing option is required")
      .optional()
  })
  .refine((data) => Object.keys(data).length > 0, {
    message: "At least one field must be provided"
  });

export const planParamsSchema = z.object({
  id: z.uuid()
});

export type PlanInput = z.infer<typeof planSchema>;
export type UpdatePlanInput = z.infer<typeof updatePlanSchema>;
export type PlanParams = z.infer<typeof planParamsSchema>;
