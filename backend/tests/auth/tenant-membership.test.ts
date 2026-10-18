import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../../src/config/database.js";
import { getActiveTenantUser } from "../../src/modules/subscription/repo/user-tenant.repo.js";

const userId = "11111111-1111-4111-8111-111111111111";
const tenantId = "22222222-2222-4222-8222-222222222222";

test("tenant membership lookup sets verified user and tenant context for RLS", async (t) => {
  const originalTransaction = prisma.$transaction;
  t.after(() => {
    (prisma as any).$transaction = originalTransaction;
  });

  let contextValues: unknown[] = [];
  let query: unknown;
  const membership = { userId, tenantId, roleKey: "admin" };
  const tx = {
    $queryRaw: async (_parts: TemplateStringsArray, ...values: unknown[]) => {
      contextValues = values;
      return [];
    },
    tenantUser: {
      findFirst: async (args: unknown) => {
        query = args;
        return membership;
      }
    }
  };
  (prisma as any).$transaction = async (operation: (arg: unknown) => unknown) =>
    operation(tx);

  const result = await getActiveTenantUser(tenantId, userId);

  assert.equal(result, membership);
  assert.ok(contextValues.includes(tenantId));
  assert.ok(contextValues.includes(userId));
  assert.deepEqual(query, {
    where: {
      userId,
      tenantId,
      removedAt: null,
      platformStatus: "active",
      tenant: { deletedAt: null, platformStatus: "active" }
    },
    include: { role: true, tenant: { select: { businessType: true } } }
  });
});
