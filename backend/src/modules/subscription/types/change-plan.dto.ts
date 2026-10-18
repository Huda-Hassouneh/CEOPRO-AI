import { z } from "zod";

export const changePlanSchema = z
  .object({
    planId: z.string().uuid("Invalid plan ID format"),

    billing_period: z.enum(
      ["monthly", "three-months", "six-months", "yearly"],
      {
        message: "Invalid billing period selected"
      }
    )
  })
  .strict();
