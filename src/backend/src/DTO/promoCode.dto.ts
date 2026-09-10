import { z } from "zod";

const discountTypeSchema = z.enum(["percentage", "fixed_amount"], {
  error: "Discount type must be percentage or fixed_amount"
});

const discountValueSchema = z
  .number()
  .positive("Discount value must be greater than 0")
  .max(99999999.99, "Discount value is too large")
  .refine(
    (value) => Number.isInteger(value * 100),
    "Discount value must have at most 2 decimal places"
  );

const promoCodeSchema = z
  .string()
  .trim()
  .min(1, "Promo code is required")
  .max(50, "Promo code must not exceed 50 characters")
  .regex(
    /^[A-Z0-9_-]+$/i,
    "Code can only contain letters, numbers, underscores, and hyphens"
  )
  .transform((value) => value.toUpperCase());

const positiveIntegerSchema = z
  .number()
  .int("Value must be an integer")
  .positive("Value must be greater than 0");

export const applyPromoCodeSchema = z
  .object({
    code: promoCodeSchema,

    plan: z.enum(["starter", "growth", "enterprise"], {
      error: "Invalid subscription plan"
    })
  })
  .strict();

export const createPromoCodeSchema = z
  .object({
    code: promoCodeSchema,

    discountType: discountTypeSchema,

    discountValue: discountValueSchema,

    maxUses: positiveIntegerSchema,

    maxUsesPerUser: positiveIntegerSchema,

    startsAt: z.coerce.date({
      error: "Invalid start date"
    }),

    expiresAt: z.coerce.date({
      error: "Invalid expiration date"
    }),

    isActive: z.boolean().default(true)
  })
  .strict()
  .superRefine((data, ctx) => {
    // Percentage discount cannot exceed 100%.
    if (data.discountType === "percentage" && data.discountValue > 100) {
      ctx.addIssue({
        code: "custom",
        path: ["discountValue"],
        message: "Percentage discount cannot exceed 100"
      });
    }

    // Expiration must be after start.
    if (data.expiresAt <= data.startsAt) {
      ctx.addIssue({
        code: "custom",
        path: ["expiresAt"],
        message: "Expiration date must be after start date"
      });
    }

    // Per-user limit cannot exceed the total limit.
    if (data.maxUsesPerUser > data.maxUses) {
      ctx.addIssue({
        code: "custom",
        path: ["maxUsesPerUser"],
        message: "Max uses per user cannot exceed max uses"
      });
    }
  });

export const updatePromoCodeSchema = z
  .object({
    code: promoCodeSchema.optional(),

    discountType: discountTypeSchema.optional(),

    discountValue: discountValueSchema.optional(),

    maxUses: positiveIntegerSchema.optional(),

    maxUsesPerUser: positiveIntegerSchema.optional(),

    startsAt: z.coerce
      .date({
        error: "Invalid start date"
      })
      .optional(),

    expiresAt: z.coerce
      .date({
        error: "Invalid expiration date"
      })
      .optional(),

    isActive: z.boolean().optional()
  })
  .strict()
  .refine((data) => Object.keys(data).length > 0, {
    message: "At least one field must be provided"
  })
  .superRefine((data, ctx) => {
    // Validate percentage discounts when both fields are supplied.
    if (
      data.discountType === "percentage" &&
      data.discountValue !== undefined &&
      data.discountValue > 100
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["discountValue"],
        message: "Percentage discount cannot exceed 100"
      });
    }

    // Compare dates only when both are supplied.
    if (
      data.startsAt !== undefined &&
      data.expiresAt !== undefined &&
      data.expiresAt <= data.startsAt
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["expiresAt"],
        message: "Expiration date must be after start date"
      });
    }

    // Compare usage limits only when both are supplied.
    if (
      data.maxUses !== undefined &&
      data.maxUsesPerUser !== undefined &&
      data.maxUsesPerUser > data.maxUses
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["maxUsesPerUser"],
        message: "Max uses per user cannot exceed max uses"
      });
    }
  });
export const promoCodePlanParamsSchema = z.object({
  promoCodeId: z.uuid(),
  planId: z.uuid()
});

export type ApplyPromoCodeDTO = z.infer<typeof applyPromoCodeSchema>;
export type CreatePromoCodeDTO = z.infer<typeof createPromoCodeSchema>;
export type UpdatePromoCodeDTO = z.infer<typeof updatePromoCodeSchema>;
export type PromoCodePlanParams = z.infer<typeof promoCodePlanParamsSchema>;
