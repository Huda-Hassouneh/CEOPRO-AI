import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../../src/config/database.js";
import {
  changePassword,
  register
} from "../../src/modules/auth/service/auth.service.js";
import {
  hashPassword,
  verifyPassword
} from "../../src/utils/token.js";

const userId = "11111111-1111-4111-8111-111111111111";
const sessionId = "33333333-3333-4333-8333-333333333333";

test("registration stores only a pending signup and sends a verification link", async (t) => {
  const originalFindUser = prisma.user.findFirst;
  const originalPendingFind = prisma.pendingSignup.findUnique;
  const originalPendingCreate = prisma.pendingSignup.create;
  const originalPendingUpdate = prisma.pendingSignup.update;
  t.after(() => {
    (prisma.user as any).findFirst = originalFindUser;
    (prisma.pendingSignup as any).findUnique = originalPendingFind;
    (prisma.pendingSignup as any).create = originalPendingCreate;
    (prisma.pendingSignup as any).update = originalPendingUpdate;
  });

  (prisma.user as any).findFirst = async () => null;
  (prisma.pendingSignup as any).findUnique = async () => null;
  let createdPasswordHash = "";
  let pendingData: any;
  (prisma.pendingSignup as any).create = async ({ data }: any) => {
    pendingData = data;
    createdPasswordHash = data.passwordHash;
    return { id: "pending-id", email: data.email, fullName: data.fullName };
  };
  (prisma.pendingSignup as any).update = async () => ({ id: "pending-id" });
  let sentEmail: any;

  const result = await register(
    {
      email: "owner@example.com",
      password: "SecurePass123",
      fullName: "New Tenant Owner",
      preferredLanguage: "en",
      businessName: "Northstar Retail",
      businessType: "retail",
      countryCode: "JO",
      primaryCurrency: "JOD",
      timezone: "Asia/Amman"
    },
    async (email) => { sentEmail = email; }
  );

  assert.equal(result.success, true);
  if (!result.success) return;
  assert.equal(result.data.verificationRequired, true);
  assert.equal("session" in result.data, false);
  assert.equal(pendingData.email, "owner@example.com");
  assert.match(pendingData.tokenHash, /^[a-f0-9]{64}$/);
  assert.notEqual(pendingData.tokenHash, sentEmail.token);
  assert.equal(sentEmail.email, "owner@example.com");
  assert.equal(
    await verifyPassword("SecurePass123", createdPasswordHash),
    true
  );
});

test("password change verifies the old password and revokes other sessions", async (t) => {
  const originalTransaction = prisma.$transaction;
  const originalFindUser = prisma.user.findUnique;
  t.after(() => {
    (prisma as any).$transaction = originalTransaction;
    (prisma.user as any).findUnique = originalFindUser;
  });

  const oldHash = await hashPassword("OldPassword123");
  (prisma.user as any).findUnique = async () => ({
    userId,
    passwordHash: oldHash,
    sessionVersion: 4
  });

  let userUpdate: any;
  let sessionUpdate: any;
  const tx = {
    $queryRaw: async () => [],
    user: {
      update: async (args: any) => {
        userUpdate = args;
        return {};
      }
    },
    authSession: {
      updateMany: async (args: any) => {
        sessionUpdate = args;
        return { count: 1 };
      }
    }
  };
  (prisma as any).$transaction = async (operation: (arg: unknown) => unknown) =>
    operation(tx);

  const result = await changePassword(
    userId,
    { currentPassword: "OldPassword123", newPassword: "NewPassword456" },
    sessionId
  );

  assert.equal(result.success, true);
  assert.deepEqual(userUpdate.where, { userId });
  assert.equal(Object.hasOwn(userUpdate.data, "sessionVersion"), false);
  assert.equal(
    await verifyPassword("NewPassword456", userUpdate.data.passwordHash),
    true
  );
  assert.equal(sessionUpdate.where.userId, userId);
  assert.deepEqual(sessionUpdate.where.id, { not: sessionId });
  assert.ok(sessionUpdate.data.revokedAt instanceof Date);
});
