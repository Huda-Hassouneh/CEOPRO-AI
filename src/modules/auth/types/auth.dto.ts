import { z } from "zod";

const emailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .pipe(z.email("A valid email address is required"))
  .pipe(z.string().max(255));

// bcrypt only hashes the first 72 bytes, so longer passwords are rejected.
const passwordSchema = z
  .string()
  .min(8, "Password must be at least 8 characters")
  .max(72, "Password cannot be longer than 72 characters")
  .regex(/[A-Za-z]/, "Password must contain at least one letter")
  .regex(/[0-9]/, "Password must contain at least one digit");

const countryCodeSchema = z
  .string()
  .trim()
  .toUpperCase()
  .pipe(
    z
      .string()
      .regex(/^[A-Z]{2}$/, "Country code must be a 2-letter ISO country code")
  );

const currencySchema = z
  .string()
  .trim()
  .toUpperCase()
  .pipe(
    z
      .string()
      .regex(/^[A-Z]{3}$/, "Currency must be a valid 3-letter uppercase code")
  );

export const registerSchema = z
  .object({
    email: emailSchema,
    password: passwordSchema,
    fullName: z.string().trim().min(1).max(150).optional(),
    preferredLanguage: z.string().trim().max(5).optional(),
    businessName: z.string().trim().min(1).max(255),
    // "platform" marks the CEOPRO owner workspace and grants platform admin
    // access, so self-registered companies must never claim it.
    businessType: z
      .string()
      .trim()
      .max(100)
      .refine((value) => value.toLowerCase() !== "platform", {
        message: "Business type is not allowed"
      })
      .optional(),
    countryCode: countryCodeSchema,
    primaryCurrency: currencySchema,
    timezone: z.string().trim().max(64).optional()
  })
  .strict();

export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Current password is required"),
    newPassword: passwordSchema
  })
  .strict()
  .refine((data) => data.currentPassword !== data.newPassword, {
    message: "New password must be different from the current password",
    path: ["newPassword"]
  });

export type RegisterInput = z.infer<typeof registerSchema>;
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;
