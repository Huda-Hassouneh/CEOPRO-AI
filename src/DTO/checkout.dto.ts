import { z } from "zod";

export const checkoutSchema = z
  .object({
    planId: z.string().uuid("Invalid plan ID format"),

    billing_period: z.enum(
      ["monthly", "three-months", "six-months", "yearly"],
      {
        message: "Invalid billing period selected"
      }
    ),

    payment_method: z.enum(["card", "stripe", "googlePay", "paypal"], {
      message: "Invalid payment provider selected"
    }),

    promoCode: z
      .string()
      .trim()
      .min(1, "Promo code cannot be empty")
      .max(50, "Promo code is too long")
      .optional()
  })
  .strict();

export type CheckoutInput = z.infer<typeof checkoutSchema>;
