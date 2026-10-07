import assert from "node:assert/strict";
import jwt from "jsonwebtoken";
import test from "node:test";
import { prisma } from "../../src/config/database.js";
import { authenticateUser } from "../../src/middleware/validators/validateUser.js";

const userId = "11111111-1111-4111-8111-111111111111";
const tenantId = "22222222-2222-4222-8222-222222222222";
const sessionId = "33333333-3333-4333-8333-333333333333";

function fakeResponse() {
  return {
    statusCode: 200,
    body: undefined as unknown,
    status(code: number) {
      this.statusCode = code;
      return this;
    },
    json(body: unknown) {
      this.body = body;
      return this;
    }
  };
}

test("a revoked login session is rejected by protected-route authentication", async (t) => {
  const oldSecret = process.env.JWT_SECRET;
  const originalFindSession = prisma.authSession.findFirst;
  t.after(() => {
    if (oldSecret === undefined) delete process.env.JWT_SECRET;
    else process.env.JWT_SECRET = oldSecret;
    (prisma.authSession as any).findFirst = originalFindSession;
  });

  process.env.JWT_SECRET = "auth-session-test-secret";
  (prisma.authSession as any).findFirst = async () => null;
  const req: any = {
    headers: {
      authorization: `Bearer ${jwt.sign(
        {
          id: userId,
          email: "owner@example.com",
          tenant_id: tenantId,
          roleKey: "owner",
          sessionId
        },
        process.env.JWT_SECRET,
        { algorithm: "HS256", expiresIn: "1h" }
      )}`
    }
  };
  const res = fakeResponse();
  let nextCalled = false;

  await authenticateUser(req, res as any, () => {
    nextCalled = true;
  });

  assert.equal(nextCalled, false);
  assert.equal(res.statusCode, 401);
});

test("an active login session passes protected-route authentication", async (t) => {
  const oldSecret = process.env.JWT_SECRET;
  const originalFindSession = prisma.authSession.findFirst;
  t.after(() => {
    if (oldSecret === undefined) delete process.env.JWT_SECRET;
    else process.env.JWT_SECRET = oldSecret;
    (prisma.authSession as any).findFirst = originalFindSession;
  });

  process.env.JWT_SECRET = "auth-session-test-secret";
  let sessionQuery: any;
  (prisma.authSession as any).findFirst = async (args: any) => {
    sessionQuery = args;
    return { id: sessionId };
  };
  const req: any = {
    headers: {
      authorization: `Bearer ${jwt.sign(
        {
          id: userId,
          email: "owner@example.com",
          tenant_id: tenantId,
          roleKey: "owner",
          sessionId
        },
        process.env.JWT_SECRET,
        { algorithm: "HS256", expiresIn: "1h" }
      )}`
    }
  };
  const res = fakeResponse();
  let nextCalled = false;

  await authenticateUser(req, res as any, () => {
    nextCalled = true;
  });

  assert.equal(nextCalled, true);
  assert.equal(req.user.id, userId);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(
    {
      id: sessionQuery.where.id,
      userId: sessionQuery.where.userId,
      tenantId: sessionQuery.where.tenantId,
      revokedAt: sessionQuery.where.revokedAt
    },
    {
    id: sessionId,
    userId,
    tenantId,
      revokedAt: null
    }
  );
  assert.ok(sessionQuery.where.expiresAt.gt instanceof Date);
});
