import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../../src/config/database.js";
import { createAccountFromVerifiedSignup } from "../../src/modules/auth/repo/auth.repo.js";

const userId = "11111111-1111-4111-8111-111111111111";
const tenantId = "22222222-2222-4222-8222-222222222222";

test("email confirmation atomically creates the account only after claiming a valid token", async (t) => {
  const originalTransaction = prisma.$transaction;
  t.after(() => {
    (prisma as any).$transaction = originalTransaction;
  });

  const events: string[] = [];
  const pending = {
    id: "pending-signup-id",
    email: "owner@example.com",
    passwordHash: "stored-password-hash",
    fullName: "New Owner",
    preferredLanguage: "en",
    businessName: "Northstar Retail",
    businessType: "retail",
    countryCode: "JO",
    primaryCurrency: "JOD",
    timezone: "Asia/Amman"
  };
  const tx = {
    pendingSignup: {
      updateMany: async () => {
        events.push("claim-token");
        return { count: 1 };
      },
      findUnique: async () => pending,
      delete: async () => { events.push("delete-pending"); return {}; }
    },
    user: {
      findFirst: async () => null,
      create: async ({ data }: any) => {
        events.push("create-user");
        assert.equal(data.passwordHash, pending.passwordHash);
        return { userId, ...data };
      }
    },
    company: {
      create: async ({ data }: any) => {
        events.push("create-company");
        return { id: tenantId, ...data };
      }
    },
    $queryRaw: async () => { events.push("set-rls-context"); return []; },
    tenantUser: {
      create: async ({ data }: any) => {
        events.push("create-owner-membership");
        assert.equal(data.roleKey, "owner");
        return { ...data, tenantId, tenant: { id: tenantId, businessName: pending.businessName } };
      }
    },
    emailVerificationGrant: {
      create: async ({ data }: any) => {
        events.push("create-exchange-grant");
        assert.equal(data.userId, userId);
        assert.equal(data.tenantId, tenantId);
        return data;
      }
    }
  };
  (prisma as any).$transaction = async (operation: (arg: unknown) => unknown) =>
    operation(tx);

  const result = await createAccountFromVerifiedSignup({
    verificationTokenHash: "a".repeat(64),
    exchangeTokenHash: "b".repeat(64),
    exchangeExpiresAt: new Date(Date.now() + 600_000)
  });

  assert.deepEqual(result, { kind: "created", exchangeTokenHash: "b".repeat(64) });
  assert.deepEqual(events, [
    "claim-token",
    "create-user",
    "create-company",
    "set-rls-context",
    "create-owner-membership",
    "create-exchange-grant",
    "delete-pending"
  ]);
});

test("an expired or consumed email token creates no user or tenant", async (t) => {
  const originalTransaction = prisma.$transaction;
  t.after(() => {
    (prisma as any).$transaction = originalTransaction;
  });
  let accountWrites = 0;
  (prisma as any).$transaction = async (operation: (arg: unknown) => unknown) =>
    operation({
      pendingSignup: {
        updateMany: async () => ({ count: 0 }),
        findUnique: async () => { accountWrites++; return null; }
      }
    });

  const result = await createAccountFromVerifiedSignup({
    verificationTokenHash: "c".repeat(64),
    exchangeTokenHash: "d".repeat(64),
    exchangeExpiresAt: new Date(Date.now() + 600_000)
  });

  assert.deepEqual(result, { kind: "invalid" });
  assert.equal(accountWrites, 0);
});
