import assert from "node:assert/strict";
import test from "node:test";
import {
  changePasswordSchema,
  registerSchema
} from "../../src/modules/auth/types/auth.dto.js";

const registration = {
  email: "  OWNER@EXAMPLE.COM ",
  password: "SecurePass123",
  fullName: "New Tenant Owner",
  businessName: "Northstar Retail",
  businessType: "retail",
  countryCode: "jo",
  primaryCurrency: "jod",
  timezone: "Asia/Amman"
};

test("registration normalizes identity and regional codes", () => {
  const parsed = registerSchema.parse(registration);
  assert.equal(parsed.email, "owner@example.com");
  assert.equal(parsed.countryCode, "JO");
  assert.equal(parsed.primaryCurrency, "JOD");
});

test("registration rejects attempts to self-register into the platform tenant", () => {
  for (const businessType of ["platform", "Platform", " PLATFORM "]) {
    assert.equal(
      registerSchema.safeParse({ ...registration, businessType }).success,
      false
    );
  }
});

test("registration accepts only the application's supported languages", () => {
  assert.equal(
    registerSchema.safeParse({ ...registration, preferredLanguage: "fr" }).success,
    false
  );
});

test("registration rejects passwords that bcrypt would truncate", () => {
  assert.equal(
    registerSchema.safeParse({
      ...registration,
      password: `${"a".repeat(70)}é1`
    }).success,
    false
  );
});

test("password change requires a different strong password", () => {
  assert.equal(
    changePasswordSchema.safeParse({
      currentPassword: "SecurePass123",
      newPassword: "SecurePass123"
    }).success,
    false
  );
  assert.equal(
    changePasswordSchema.safeParse({
      currentPassword: "old",
      newPassword: "AnotherPass456"
    }).success,
    true
  );
});
