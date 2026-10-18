import { z } from "zod";

const countryCodes = [
  "BE", "FR", "LU", "MD", "PL", "RO", "SK", "ES", "BW", "BF", "CM",
  "CF", "CI", "CD", "EG", "GN", "GW", "JO", "LR", "ML", "MA", "SN",
  "SL", "TN"
] as const;

export const regionalPreferencesSchema = z.object({
  country: z.enum(countryCodes),
  city: z.string().trim().min(1).max(100),
  language: z.enum(["en", "ar"])
}).strict();

export const profileSchema = z.object({
  industry: z.enum(["retail", "tech", "manufacturing", "restaurants", "healthcare", "other"]),
  businessSize: z.enum(["1-50", "51-200", "201+"]).optional(),
  annualRevenue: z.enum(["under-100k", "100k-500k", "500k-1m", "1m-10m", "10m-50m", "50m+"]).optional(),
  completedStep: z.union([z.literal(2), z.literal(3)])
}).strict().superRefine((value, context) => {
  if (value.completedStep === 3 && (!value.businessSize || !value.annualRevenue)) {
    context.addIssue({ code: "custom", message: "Business size and annual revenue are required", path: ["businessSize"] });
  }
});

export const goalsSchema = z.object({
  objectives: z.array(z.enum(["competitors", "forecasting", "knowledge"])).min(1).max(3)
}).strict();

export const planSchema = z.object({
  selectedPlan: z.enum(["standard", "pro", "custom"]),
  checkoutMode: z.enum(["trial", "paid"]),
  billingPeriod: z.enum(["monthly", "three-months", "six-months"]),
  customPlan: z.record(
    z.string(),
    z.union([z.number().nonnegative(), z.string().trim().max(100), z.boolean()])
  ).optional()
}).strict();

const sourceStatusSchema = z.object({
  status: z.enum(["not-connected", "connecting", "connected", "error"]),
  error: z.string().max(500)
}).strict();

export const completeOnboardingSchema = z.object({
  sourceStatuses: z.record(z.string(), sourceStatusSchema),
  websiteUrl: z.union([z.url().max(2048), z.literal("")]),
  databaseProvider: z.string().trim().max(50),
  downloadedTemplates: z.array(z.string().trim().min(1).max(100)).max(20)
}).strict();

export type RegionalPreferencesInput = z.infer<typeof regionalPreferencesSchema>;
export type ProfileInput = z.infer<typeof profileSchema>;
export type GoalsInput = z.infer<typeof goalsSchema>;
export type PlanInput = z.infer<typeof planSchema>;
export type CompleteOnboardingInput = z.infer<typeof completeOnboardingSchema>;
