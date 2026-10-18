import assert from "node:assert/strict";
import test from "node:test";
import { selectLoginMembership } from "../../src/modules/auth/service/login-membership.js";

const customerAdmin = {
  roleKey: "admin",
  tenantId: "customer-tenant",
  tenant: { businessType: "retail" }
};

const platformAdmin = {
  roleKey: "admin",
  tenantId: "platform-tenant",
  tenant: { businessType: "platform" }
};

test("customer membership wins over a platform membership for customer admins", () => {
  const selected = selectLoginMembership([platformAdmin, customerAdmin]);
  assert.equal(selected.tenantId, "customer-tenant");
});

test("platform owner membership selects the platform workspace", () => {
  const platformOwner = { ...platformAdmin, roleKey: "owner" };
  const selected = selectLoginMembership([customerAdmin, platformOwner]);
  assert.equal(selected.tenantId, "platform-tenant");
});

test("platform-only admins retain their platform workspace", () => {
  const selected = selectLoginMembership([platformAdmin]);
  assert.equal(selected.tenantId, "platform-tenant");
});
