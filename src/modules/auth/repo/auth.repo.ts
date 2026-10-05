import { prisma } from "../../../config/database.js";

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
    where: { userId, tenantId, removedAt: null },
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

export async function createUserWithCompany(input: CreateUserWithCompanyInput) {
  const language = input.preferredLanguage ?? "en";

  return prisma.$transaction(async (tx) => {
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

    const membership = await tx.tenantUser.create({
      data: { tenantId: company.id, userId: user.userId, roleKey: "owner" },
      include: { tenant: true }
    });

    return { user, membership };
  });
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
  return prisma.$transaction([
    prisma.user.update({
      where: { userId },
      data: { passwordHash, sessionVersion: { increment: 1 } }
    }),
    prisma.authSession.updateMany({
      where: {
        userId,
        revokedAt: null,
        ...(keepSessionId ? { id: { not: keepSessionId } } : {})
      },
      data: { revokedAt: new Date() }
    })
  ]);
}
