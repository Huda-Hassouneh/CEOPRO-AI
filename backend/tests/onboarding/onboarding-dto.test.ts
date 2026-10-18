import assert from "node:assert/strict";
import test from "node:test";
import {
  completeOnboardingSchema,
  goalsSchema,
  planSchema,
  profileSchema,
  regionalPreferencesSchema
} from "../../src/modules/onboarding/types/onboarding.dto.js";

test("regional preferences accept supported country/language and reject unknown values", () => {
  assert.equal(
    regionalPreferencesSchema.safeParse({
      country: "JO",
      city: "Amman",
      language: "ar"
    }).success,
    true
  );
  assert.equal(
    regionalPreferencesSchema.safeParse({
      country: "US",
      city: "Amman",
      language: "ar"
    }).success,
    false
  );
});

test("profile validation requires business size and revenue for step three", () => {
  assert.equal(
    profileSchema.safeParse({ industry: "retail", completedStep: 2 }).success,
    true
  );
  assert.equal(
    profileSchema.safeParse({ industry: "retail", completedStep: 3 }).success,
    false
  );
  assert.equal(
    profileSchema.safeParse({
      industry: "retail",
      businessSize: "1-50",
      annualRevenue: "100k-500k",
      completedStep: 3
    }).success,
    true
  );
});

test("goals and plan reject unsupported enum values and extra fields", () => {
  assert.equal(goalsSchema.safeParse({ objectives: ["forecasting"] }).success, true);
  assert.equal(goalsSchema.safeParse({ objectives: ["admin"] }).success, false);
  assert.equal(
    planSchema.safeParse({
      selectedPlan: "enterprise",
      checkoutMode: "paid",
      billingPeriod: "monthly"
    }).success,
    false
  );
  assert.equal(
    planSchema.safeParse({
      selectedPlan: "pro",
      checkoutMode: "paid",
      billingPeriod: "monthly",
      ignored: true
    }).success,
    false
  );
});

test("completion validation bounds source metadata and template names", () => {
  assert.equal(
    completeOnboardingSchema.safeParse({
      sourceStatuses: {
        website: { status: "connected", error: "" }
      },
      websiteUrl: "https://example.com",
      databaseProvider: "postgresql",
      downloadedTemplates: ["sales.csv"]
    }).success,
    true
  );
  assert.equal(
    completeOnboardingSchema.safeParse({
      sourceStatuses: {
        website: { status: "connected", error: "" }
      },
      websiteUrl: "not-a-url",
      databaseProvider: "postgresql",
      downloadedTemplates: []
    }).success,
    false
  );
});
