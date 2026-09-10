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

const trialPeriodSchema = z
  .object({
    trialPeriodValue: z.number().int().nonnegative().default(0),
    trialPeriodUnit: intervalUnitSchema.nullable().optional()
  })
  .refine(
    (data) =>
      (data.trialPeriodValue === 0 &&
        (data.trialPeriodUnit === null ||
          data.trialPeriodUnit === undefined)) ||
      (data.trialPeriodValue > 0 &&
        data.trialPeriodUnit !== null &&
        data.trialPeriodUnit !== undefined),
    {
      message:
        "trialPeriodUnit is required when trialPeriodValue is greater than 0",
      path: ["trialPeriodUnit"]
    }
  );

export const planSchema = z
  .object({
    name: z.enum(["starter", "growth", "enterprise"]),

    description: z.string().optional(),

    price: priceSchema,

    currency: currencySchema,

    billingIntervalValue: z.number().int().positive(),

    billingIntervalUnit: intervalUnitSchema,

    isActive: z.boolean().default(true)
  })
  .and(trialPeriodSchema);

export const updatePlanSchema = z
  .object({
    name: z.enum(["starter", "growth", "enterprise"]).optional(),

    description: z.string().optional(),

    price: priceSchema.optional(),

    currency: currencySchema.optional(),

    billingIntervalValue: z.number().int().positive().optional(),

    billingIntervalUnit: intervalUnitSchema.optional(),

    trialPeriodValue: z.number().int().nonnegative().optional(),

    trialPeriodUnit: intervalUnitSchema.nullable().optional(),

    isActive: z.boolean().optional()
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
