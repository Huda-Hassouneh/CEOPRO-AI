import bcrypt from "bcryptjs";
import { prisma } from "../../../src/config/database.js";
import { companies, roles } from "../data/catalog.js";
import type { SeedClock } from "../helpers/time.js";
import { sha256 } from "../helpers/ids.js";

export async function seedIdentityAndAccess(args: {
  uuid: (key: string) => string;
  password: string;
  clock: SeedClock;
}) {
  const { uuid, password, clock } = args;

  const installed = await prisma.systemRole.findMany({
    where: { roleKey: { in: [...roles] } }
  });

  if (installed.length !== roles.length) {
    throw new Error(
      "Migrated system_roles are missing; apply the canonical migration chain first."
    );
  }

  const passwordHash = await bcrypt.hash(password, 12);
  const tenantIds = companies.map((_, index) => uuid(`tenant:${index}`));

  await prisma.company.createMany({
    data: companies.map(
      ([businessName, countryCode, primaryCurrency, timezone], index) => ({
        id: tenantIds[index],
        businessName,
        businessType: index === 2 ? "Food retail" : "Retail",
        countryCode,
        primaryCurrency,
        supportedCurrencies: [primaryCurrency],
        timezone,
        platformStatus: index === 5 ? "suspended" : "active"
      })
    ),
    skipDuplicates: true
  });

  const users = companies.flatMap((_, tenantIndex) =>
    roles.map((role, roleIndex) => ({
      userId: uuid(`user:${tenantIndex}:${roleIndex}`),
      email: `${role}.${tenantIndex + 1}@example.com`,
      fullName: `${["Maya", "Omar", "Lina", "Samir", "Nour"][roleIndex]} ${["Haddad", "Nasser", "Salem", "Khalil", "Farah", "Karim"][tenantIndex]}`,
      passwordHash
    }))
  );

  await prisma.user.createMany({ data: users, skipDuplicates: true });

  await prisma.tenantUser.createMany({
    data: users.map((user, index) => ({
      id: uuid(`membership:${index}`),
      tenantId: tenantIds[Math.floor(index / roles.length)],
      userId: user.userId,
      roleKey: roles[index % roles.length],
      removedAt: index === 29 ? clock.ago(8) : null
    })),
    skipDuplicates: true
  });

  await prisma.authSession.createMany({
    data: users.map((user, index) => ({
      id: uuid(`session:${index}`),
      userId: user.userId,
      tenantId: tenantIds[Math.floor(index / roles.length)],
      device: "Development browser",
      expiresAt: clock.ago(index % 7 === 0 ? 2 : -30),
      revokedAt: index % 9 === 0 ? clock.ago(2) : null
    })),
    skipDuplicates: true
  });

  await prisma.platformInvitation.createMany({
    data: tenantIds.flatMap((tenantId, tenantIndex) =>
      [0, 1].map((invitationIndex) => ({
        id: uuid(`invitation:${tenantIndex}:${invitationIndex}`),
        tenantId,
        email: `invite.${tenantIndex + 1}.${invitationIndex + 1}@example.com`,
        roleKey: invitationIndex ? "manager" : "staff",
        invitedBy: users[tenantIndex * roles.length].userId,
        tokenHash: sha256(
          `ceopro-invitation-fixture:${tenantIndex}:${invitationIndex}`
        ),
        status: "pending",
        expiresAt: clock.ago(invitationIndex ? 5 : -10)
      }))
    ),
    skipDuplicates: true
  });

  return { tenantIds, users };
}
