import jwt from "jsonwebtoken";
import { createHash, randomBytes } from "node:crypto";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type {
  Company,
  TenantUser,
  User
} from "../../../generated/prisma/client.js";
import type { ServiceResult } from "../../../types/service.js";
import {
  generateAccessToken,
  hashPassword,
  verifyPassword
} from "../../../utils/token.js";
import type { ChangePasswordInput, RegisterInput } from "../types/auth.dto.js";
import * as repo from "../repo/auth.repo.js";
import { sendVerificationEmail } from "../../../integrations/email/email.service.js";

type MembershipWithTenant = TenantUser & { tenant: Company };

function isUniqueViolation(error: unknown): boolean {
  const code = (error as { code?: string })?.code;
  return code === "P2002" || code === "23505";
}

/**
 * Persists an auth session and returns the login response body. Used after
 * normal login and after the one-time email-verification exchange.
 */
export async function issueSession(
  user: User,
  membership: MembershipWithTenant,
  device: string
) {
  const session = await repo.createSession({
    userId: user.userId,
    tenantId: membership.tenantId,
    device: device.slice(0, 255),
    expiresAt: new Date(Date.now() + 3600_000)
  });
  const accessToken = generateAccessToken({
    user_id: user.userId,
    id: user.userId,
    email: user.email,
    tenant_id: membership.tenantId,
    roleKey: membership.roleKey,
    sessionId: session.id,
    sessionVersion: user.sessionVersion
  });
  const decoded = jwt.decode(accessToken);
  if (
    decoded &&
    typeof decoded !== "string" &&
    typeof decoded.exp === "number"
  ) {
    await repo.updateSessionExpiry(session.id, new Date(decoded.exp * 1000));
  }

  return {
    session: {
      accessToken,
      refreshToken: null,
      tenantId: membership.tenantId,
      roleKey: membership.roleKey,
      roles: [membership.roleKey],
      user: {
        id: user.userId,
        email: user.email,
        fullName: user.fullName,
        preferredLanguage: user.preferredLanguage,
        company: {
          id: membership.tenant.id,
          business_name: membership.tenant.businessName,
          business_type: membership.tenant.businessType,
          country_code: membership.tenant.countryCode,
          primary_currency: membership.tenant.primaryCurrency
        }
      }
    }
  };
}

const REGISTRATION_TOKEN_TTL_MS = 30 * 60_000;
const VERIFICATION_GRANT_TTL_MS = 10 * 60_000;
const VERIFICATION_RESEND_COOLDOWN_MS = 30_000;

function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function makeOpaqueToken(): string {
  return randomBytes(32).toString("hex");
}

function verificationAccepted(email: string) {
  return {
    success: true as const,
    data: { email, verificationRequired: true },
    message:
      "If the address can be registered, a verification email has been sent."
  };
}

async function sendPendingSignupEmail(
  pending: { id: string; email: string; fullName: string | null },
  verificationToken: string,
  sendEmail: typeof sendVerificationEmail
) {
  await sendEmail({
    email: pending.email,
    fullName: pending.fullName ?? undefined,
    token: verificationToken
  });
  await repo.markPendingSignupEmailSent(pending.id, new Date());
}

export async function register(
  input: RegisterInput,
  sendEmail: typeof sendVerificationEmail = sendVerificationEmail
): Promise<ServiceResult<{ email: string; verificationRequired: boolean }>> {
  // Keep the response the same for existing, pending, and new email addresses
  // to avoid exposing whether a user account already exists.
  if (await repo.findUserByEmail(input.email)) {
    return verificationAccepted(input.email);
  }

  let pending = await repo.findPendingSignupByEmail(input.email);
  const now = new Date();
  if (pending && pending.expiresAt.getTime() <= now.getTime()) {
    await repo.deletePendingSignup(pending.id);
    pending = null;
  }
  if (
    pending?.lastEmailSentAt &&
    now.getTime() - pending.lastEmailSentAt.getTime() <
      VERIFICATION_RESEND_COOLDOWN_MS
  ) {
    return verificationAccepted(input.email);
  }

  const verificationToken = makeOpaqueToken();
  try {
    if (pending) {
      pending = await repo.rotatePendingSignupToken(
        pending.id,
        tokenHash(verificationToken),
        new Date(now.getTime() + REGISTRATION_TOKEN_TTL_MS)
      );
    } else {
      pending = await repo.createPendingSignup({
        email: input.email,
        passwordHash: await hashPassword(input.password),
        fullName: input.fullName,
        preferredLanguage: input.preferredLanguage,
        businessName: input.businessName,
        businessType: input.businessType,
        countryCode: input.countryCode,
        primaryCurrency: input.primaryCurrency,
        timezone: input.timezone,
        tokenHash: tokenHash(verificationToken),
        expiresAt: new Date(now.getTime() + REGISTRATION_TOKEN_TTL_MS)
      });
    }
    await sendPendingSignupEmail(pending, verificationToken, sendEmail);
  } catch (error) {
    if (isUniqueViolation(error)) {
      // A concurrent signup won the unique email constraint. Keep the public
      // response generic; the other request owns sending the verification.
      return verificationAccepted(input.email);
    }
    console.error("Email verification delivery failed:", error);
    return { success: false, code: ERROR_CODES.EMAIL_DELIVERY_FAILED };
  }

  return verificationAccepted(input.email);
}

export async function resendVerification(
  email: string,
  sendEmail: typeof sendVerificationEmail = sendVerificationEmail
) {
  if (await repo.findUserByEmail(email)) {
    return verificationAccepted(email);
  }
  const pending = await repo.findPendingSignupByEmail(email);
  if (!pending) return verificationAccepted(email);

  const now = new Date();
  if (
    pending.lastEmailSentAt &&
    now.getTime() - pending.lastEmailSentAt.getTime() <
      VERIFICATION_RESEND_COOLDOWN_MS
  ) {
    return verificationAccepted(email);
  }

  const verificationToken = makeOpaqueToken();
  try {
    const rotated = await repo.rotatePendingSignupToken(
      pending.id,
      tokenHash(verificationToken),
      new Date(now.getTime() + REGISTRATION_TOKEN_TTL_MS)
    );
    await sendPendingSignupEmail(rotated, verificationToken, sendEmail);
  } catch (error) {
    console.error("Email verification resend failed:", error);
    return { success: false as const, code: ERROR_CODES.EMAIL_DELIVERY_FAILED };
  }
  return verificationAccepted(email);
}

export async function confirmEmail(token: string) {
  const exchangeCode = makeOpaqueToken();
  const result = await repo.createAccountFromVerifiedSignup({
    verificationTokenHash: tokenHash(token),
    exchangeTokenHash: tokenHash(exchangeCode),
    exchangeExpiresAt: new Date(Date.now() + VERIFICATION_GRANT_TTL_MS)
  });

  if (result.kind === "invalid") {
    return {
      success: false as const,
      code: ERROR_CODES.EMAIL_VERIFICATION_INVALID
    };
  }

  if (result.kind === "already_registered") {
    // The token may be valid, but this email already belongs to an account.
    // Do not mislabel that case as an expired or invalid verification link.
    return {
      success: false as const,
      code: "EMAIL_ALREADY_REGISTERED" as const,
      message:
        "An account already exists with this email. Sign in or reset your password."
    };
  }

  return { success: true as const, data: { code: exchangeCode } };
}

export async function exchangeVerificationCode(code: string) {
  const verified = await repo.consumeEmailVerificationGrant(tokenHash(code));
  if (!verified) {
    return {
      success: false as const,
      code: ERROR_CODES.EMAIL_VERIFICATION_INVALID
    };
  }
  return {
    success: true as const,
    data: await issueSession(
      verified.user,
      verified.membership,
      "Email verification"
    )
  };
}

export async function me(userId: string, tenantId: string) {
  const user = await repo.findUserById(userId);
  if (!user) {
    return { success: false as const, code: ERROR_CODES.USER_NOT_FOUND };
  }

  const membership = await repo.findMembership(userId, tenantId);
  if (!membership) {
    return { success: false as const, code: ERROR_CODES.TENANT_ACCESS_DENIED };
  }

  const memberships = await repo.findActiveMemberships(userId);

  return {
    success: true as const,
    data: {
      user: {
        id: user.userId,
        email: user.email,
        fullName: user.fullName,
        preferredLanguage: user.preferredLanguage,
        createdAt: user.createdAt
      },
      membership: {
        tenantId: membership.tenantId,
        roleKey: membership.roleKey,
        roleName: membership.role.roleName,
        businessName: membership.tenant.businessName
      },
      memberships: memberships.map((m) => ({
        tenantId: m.tenantId,
        roleKey: m.roleKey,
        businessName: m.tenant.businessName
      }))
    }
  };
}

export async function changePassword(
  userId: string,
  input: ChangePasswordInput,
  currentSessionId?: string
): Promise<ServiceResult<{ userId: string }>> {
  const user = await repo.findUserById(userId);
  if (!user) {
    return { success: false, code: ERROR_CODES.USER_NOT_FOUND };
  }

  if (!(await verifyPassword(input.currentPassword, user.passwordHash))) {
    return { success: false, code: ERROR_CODES.INVALID_CREDENTIALS };
  }

  await repo.updatePassword(
    userId,
    await hashPassword(input.newPassword),
    currentSessionId
  );

  return {
    success: true,
    data: { userId },
    message: "Password changed successfully"
  };
}
