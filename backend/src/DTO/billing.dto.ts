import { z } from "zod";

// --- Route Parameter Schemas ---
export const planIdParamSchema = z.object({
  plan_id: z.string().uuid("Invalid plan_id format. Must be a valid UUID.")
});

export const planAndFeatureIdParamSchema = z.object({
  plan_id: z.string().uuid("Invalid plan_id format. Must be a valid UUID."),
  feature_id: z
    .string()
    .uuid("Invalid feature_id format. Must be a valid UUID.")
});

export const linkFeatureBodySchema = z
  .object({
    feature_id: z
      .string({ error: "feature_id is required" })
      .uuid("Invalid feature_id format."),
    limit_value: z
      .number()
      .int("limit_value must be an integer")
      .min(0, "limit_value cannot be negative")
      .nullable()
      .optional() // null represents 'unlimited'
  })
  .strict();

export const updateFeatureLimitsBodySchema = z
  .object({
    limit_value: z
      .number({ error: "limit_value is required (send null for unlimited)" })
      .int("limit_value must be an integer")
      .min(0, "limit_value cannot be negative")
      .nullable()
  })
  .strict();
