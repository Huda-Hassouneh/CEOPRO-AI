import { z } from "zod";

export const checkoutSchema = z
  .object({
    planId: z.uuid(),

    promoCode: z
      .string()
      .trim()
      .min(1, "Promo code cannot be empty")
      .max(50, "Promo code is too long")
      .optional()
  })
  .strict();
