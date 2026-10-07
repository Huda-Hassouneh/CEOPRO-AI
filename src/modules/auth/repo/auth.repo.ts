import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";

export async function findUserByEmail(email: string) {
  return prisma.user.findFirst({
    where: { email: { equals: email, mode: "insensitive" } }
  });
}

export async function findUserById(userId: string) {
  return prisma.user.findUnique({ where: { userId } });
}

export async function findMembership(userId: string, tenantId: string) {
  return prisma.tenantUser.findFirst({
    where: {
      userId,
      tenantId,
      removedAt: null,
      platformStatus: "active",
      tenant: { deletedAt: null, platformStatus: "active" }
    },
    include: { role: true, tenant: true }
  });
}

export async function findActiveMemberships(userId: string) {
  return prisma.tenantUser.findMany({
    where: {
      userId,
      removedAt: null,
      platformStatus: "active",
      tenant: { deletedAt: null, platformStatus: "active" }
    },
    include: { tenant: true },
    orderBy: { joinedAt: "asc" }
  });
}

export interface CreateUserWithCompanyInput {
  email: string;
  passwordHash: string;
  fullName?: string;
  preferredLanguage?: string;
  businessName: string;
  businessType?: string;
  countryCode: string;
  primaryCurrency: string;
  timezone?: string;
}

type TenantCreationTransaction = Prisma.TransactionClient;

async function createTenantAccount(
  tx: TenantCreationTransaction,
  input: CreateUserWithCompanyInput
) {
  const language = input.preferredLanguage ?? "en";
  const user = await tx.user.create({
    data: {
      email: input.email,
      passwordHash: input.passwordHash,
      fullName: input.fullName,
      preferredLanguage: language
    }
  });

  const company = await tx.company.create({
    data: {
      businessName: input.businessName,
      businessType: input.businessType,
      countryCode: input.countryCode,
      operatingCountries: [input.countryCode],
      primaryCurrency: input.primaryCurrency,
      supportedCurrencies: [input.primaryCurrency],
      preferredLanguage: language,
      supportedLanguages: [language],
      ...(input.timezone ? { timezone: input.timezone } : {})
    }
  });

  // The first tenant membership is allowed only for the user and tenant
  // recorded in transaction-local RLS context.
  await tx.$queryRaw`
    SELECT
      set_config('app.current_tenant_id', ${company.id}, true),
      set_config('app.current_user_id', ${user.userId}, true)
  `;

  const membership = await tx.tenantUser.create({
    data: { tenantId: company.id, userId: user.userId, roleKey: "owner" },
    include: { tenant: true }
  });

  return { user, membership };
}

export async function createUserWithCompany(input: CreateUserWithCompanyInput) {
  return prisma.$transaction((tx) => createTenantAccount(tx, input));
}

export async function createSession(input: {
  userId: string;
  tenantId: string;
  device: string;
  expiresAt: Date;
}) {
  return prisma.authSession.create({ data: input });
}

export async function updateSessionExpiry(sessionId: string, expiresAt: Date) {
  return prisma.authSession.update({
    where: { id: sessionId },
    data: { expiresAt }
  });
}

// Rotates the password and signs the user out of every other session.
export async function updatePassword(
  userId: string,
  passwordHash: string,
  keepSessionId?: string
) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT set_config('app.current_user_id', ${userId}, true)
    `;
    await tx.user.update({
      where: { userId },
      data: { passwordHash }
    });
    await tx.authSession.updateMany({
      where: {
        userId,
        revokedAt: null,
        ...(keepSessionId ? { id: { not: keepSessionId } } : {})
      },
      data: { revokedAt: new Date() }
    });
  });
}

export interface PendingSignupInput extends CreateUserWithCompanyInput {
  email: string;
  passwordHash: string;
  tokenHash: string;
  expiresAt: Date;
}

export function findPendingSignupByEmail(email: string) {
  return prisma.pendingSignup.findUnique({ where: { email } });
}

export function createPendingSignup(input: PendingSignupInput) {
  return prisma.pendingSignup.create({
    data: {
      email: input.email,
      passwordHash: input.passwordHash,
      fullName: input.fullName,
      preferredLanguage: input.preferredLanguage ?? "en",
      businessName: input.businessName,
      businessType: input.businessType,
      countryCode: input.countryCode,
      primaryCurrency: input.primaryCurrency,
      timezone: input.timezone ?? "Asia/Amman",
      tokenHash: input.tokenHash,
      expiresAt: input.expiresAt
    }
  });
}

export function deletePendingSignup(id: string) {
  return prisma.pendingSignup.delete({ where: { id } });
}

export function rotatePendingSignupToken(
  id: string,
  tokenHash: string,
  expiresAt: Date
) {
  return prisma.pendingSignup.update({
    where: { id },
    data: { tokenHash, expiresAt, consumedAt: null }
  });
}

export function markPendingSignupEmailSent(id: string, sentAt: Date) {
  return prisma.pendingSignup.update({
    where: { id },
    data: { lastEmailSentAt: sentAt }
  });
}

export async function createAccountFromVerifiedSignup(input: {
  verificationTokenHash: string;
  exchangeTokenHash: string;
  exchangeExpiresAt: Date;
}): Promise<
  | { kind: "invalid" }
  | { kind: "already_registered" }
  | { kind: "created"; exchangeTokenHash: string }
> {
  const now = new Date();
  return prisma.$transaction(async (tx) => {
    const claimed = await tx.pendingSignup.updateMany({
      where: {
        tokenHash: input.verificationTokenHash,
        expiresAt: { gt: now },
        consumedAt: null
      },
      data: { consumedAt: now }
    });
    if (claimed.count !== 1) return { kind: "invalid" as const };

    const pending = await tx.pendingSignup.findUnique({
      where: { tokenHash: input.verificationTokenHash }
    });
    if (!pending) return { kind: "invalid" as const };

    const existingUser = await tx.user.findFirst({
      where: { email: { equals: pending.email, mode: "insensitive" } },
      select: { userId: true }
    });
    if (existingUser) {
      await tx.pendingSignup.delete({ where: { id: pending.id } });
      return { kind: "already_registered" as const };
    }

    const { user, membership } = await createTenantAccount(tx, {
      email: pending.email,
      passwordHash: pending.passwordHash,
      fullName: pending.fullName ?? undefined,
      preferredLanguage: pending.preferredLanguage,
      businessName: pending.businessName,
      businessType: pending.businessType ?? undefined,
      countryCode: pending.countryCode,
      primaryCurrency: pending.primaryCurrency,
      timezone: pending.timezone
    });
    await tx.emailVerificationGrant.create({
      data: {
        tokenHash: input.exchangeTokenHash,
        userId: user.userId,
        tenantId: membership.tenantId,
        expiresAt: input.exchangeExpiresAt
      }
    });
    await tx.pendingSignup.delete({ where: { id: pending.id } });

    return { kind: "created" as const, exchangeTokenHash: input.exchangeTokenHash };
  });
}

export async function consumeEmailVerificationGrant(tokenHash: string) {
  const now = new Date();
  return prisma.$transaction(async (tx) => {
    const consumed = await tx.emailVerificationGrant.updateMany({
      where: { tokenHash, consumedAt: null, expiresAt: { gt: now } },
      data: { consumedAt: now }
    });
    if (consumed.count !== 1) return null;

    const grant = await tx.emailVerificationGrant.findUnique({
      where: { tokenHash },
      include: { user: true }
    });
    if (!grant) return null;

    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${grant.tenantId}, true),
        set_config('app.current_user_id', ${grant.userId}, true)
    `;
    const membership = await tx.tenantUser.findFirst({
      where: {
        userId: grant.userId,
        tenantId: grant.tenantId,
        removedAt: null,
        platformStatus: "active",
        tenant: { deletedAt: null, platformStatus: "active" }
      },
      include: { tenant: true }
    });
    if (!membership) {
      throw new InvalidEmailVerificationGrantError();
    }
    return { user: grant.user, membership };
  }).catch((error: unknown) => {
    if (error instanceof InvalidEmailVerificationGrantError) return null;
    throw error;
  });
}

class InvalidEmailVerificationGrantError extends Error {}
