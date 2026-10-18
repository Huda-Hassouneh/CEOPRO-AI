import { randomUUID } from "node:crypto";
import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";

const AUTH_TRANSACTION_OPTIONS = { maxWait: 10_000, timeout: 15_000 } as const;

export async function findUserByEmail(email: string) {
  return prisma.$transaction(async (tx) => {
    // Unauthenticated auth flows do not yet have app.current_user_id or a
    // tenant context. The users RLS policy grants this narrowly scoped lookup
    // only for the email placed in transaction-local app.auth_email.
    await tx.$queryRaw`
      SELECT set_config('app.auth_email', ${email}, true)
    `;

    return tx.user.findFirst({
      where: { email: { equals: email, mode: "insensitive" } }
    });
  }, AUTH_TRANSACTION_OPTIONS);
}

export type LoginMembership = {
  tenantId: string;
  roleKey: string;
  tenant: {
    id: string;
    businessType: string | null;
    businessName: string;
    countryCode: string;
    primaryCurrency: string;
  };
};

/**
 * Load only the active workspaces needed to issue a login session. The
 * database function has a fixed search path, checks the transaction-local
 * user and email context, and returns only membership and tenant fields.
 */
export async function findLoginMemberships(
  userId: string,
  email: string
): Promise<LoginMembership[]> {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.auth_email', ${email}, true),
        set_config('app.current_user_id', ${userId}, true)
    `;

    const rows = await tx.$queryRaw<
      {
        tenant_id: string;
        role_key: string;
        business_type: string | null;
        business_name: string;
        country_code: string;
        primary_currency: string;
      }[]
    >`SELECT * FROM public.auth_login_memberships(${userId}::uuid)`;

    return rows.map((row) => ({
      tenantId: row.tenant_id,
      roleKey: row.role_key,
      tenant: {
        id: row.tenant_id,
        businessType: row.business_type,
        businessName: row.business_name,
        countryCode: row.country_code,
        primaryCurrency: row.primary_currency
      }
    }));
  }, AUTH_TRANSACTION_OPTIONS);
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

class DuplicateSignupEmailError extends Error {}

function isEmailUniqueConstraintError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("code" in error)) {
    return false;
  }
  const prismaError = error as {
    code?: unknown;
    message?: unknown;
    meta?: { target?: unknown };
  };
  if (prismaError.code !== "P2002") return false;

  const target = String(prismaError.meta?.target ?? "").toLowerCase();
  const message = String(prismaError.message ?? "").toLowerCase();
  return target.includes("email") || message.includes("uq_users_email_lower");
}

async function createTenantAccount(
  tx: TenantCreationTransaction,
  input: CreateUserWithCompanyInput
) {
  const language = input.preferredLanguage ?? "en";
  const userId = randomUUID();
  const tenantId = randomUUID();

  // Prisma returns created rows from INSERT ... RETURNING. Establish both
  // ids first so the signup-specific RLS policies can permit the new user
  // and tenant rows to be returned before their first membership exists.
  await tx.$queryRaw`
    SELECT
      set_config('app.current_user_id', ${userId}, true),
      set_config('app.current_tenant_id', ${tenantId}, true)
  `;

  const user = await tx.user.create({
    data: {
      userId,
      email: input.email,
      passwordHash: input.passwordHash,
      fullName: input.fullName,
      preferredLanguage: language
    }
  });

  await tx.company.create({
    data: {
      id: tenantId,
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
  // recorded in transaction-local RLS context. The context was established
  // before creating either row because Prisma uses INSERT ... RETURNING.
  const membership = await tx.tenantUser.create({
    data: { tenantId, userId: user.userId, roleKey: "owner" },
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
  try {
    return await prisma.$transaction(async (tx) => {
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

      await tx.$queryRaw`
        SELECT set_config('app.auth_email', ${pending.email}, true)
      `;
      const existingUser = await tx.user.findFirst({
        where: { email: { equals: pending.email, mode: "insensitive" } },
        select: { userId: true }
      });
      if (existingUser) {
        await tx.pendingSignup.delete({ where: { id: pending.id } });
        return { kind: "already_registered" as const };
      }

      let account: Awaited<ReturnType<typeof createTenantAccount>>;
      try {
        account = await createTenantAccount(tx, {
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
      } catch (error) {
        // RLS can hide an existing user from the pre-check. The unique index
        // is authoritative; roll back and map its email conflict below.
        if (isEmailUniqueConstraintError(error)) {
          throw new DuplicateSignupEmailError();
        }
        throw error;
      }

      await tx.emailVerificationGrant.create({
        data: {
          tokenHash: input.exchangeTokenHash,
          userId: account.user.userId,
          tenantId: account.membership.tenantId,
          expiresAt: input.exchangeExpiresAt
        }
      });
      await tx.pendingSignup.delete({ where: { id: pending.id } });

      return {
        kind: "created" as const,
        exchangeTokenHash: input.exchangeTokenHash
      };
    });
  } catch (error) {
    if (!(error instanceof DuplicateSignupEmailError)) throw error;

    // The failed transaction rolled back the token claim. Remove this stale
    // pending signup outside that transaction before returning the safe result.
    await prisma.pendingSignup.deleteMany({
      where: { tokenHash: input.verificationTokenHash }
    });
    return { kind: "already_registered" as const };
  }
}

export async function consumeEmailVerificationGrant(tokenHash: string) {
  const now = new Date();
  return prisma
    .$transaction(async (tx) => {
      const consumed = await tx.emailVerificationGrant.updateMany({
        where: { tokenHash, consumedAt: null, expiresAt: { gt: now } },
        data: { consumedAt: now }
      });
      if (consumed.count !== 1) return null;

      // Read only the grant's ids first. Loading `user` via the relation here
      // would run before app.current_user_id is set, so forced RLS can hide it
      // and Prisma may return a null relation.
      const grant = await tx.emailVerificationGrant.findUnique({
        where: { tokenHash },
        select: { userId: true, tenantId: true }
      });
      if (!grant) throw new InvalidEmailVerificationGrantError();

      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${grant.tenantId}, true),
          set_config('app.current_user_id', ${grant.userId}, true)
      `;

      const user = await tx.user.findUnique({
        where: { userId: grant.userId }
      });
      if (!user) throw new InvalidEmailVerificationGrantError();

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
      return { user, membership };
    })
    .catch((error: unknown) => {
      if (error instanceof InvalidEmailVerificationGrantError) return null;
      throw error;
    });
}

class InvalidEmailVerificationGrantError extends Error {}
