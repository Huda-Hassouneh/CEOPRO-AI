import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  isPlatformPrincipal,
  isPlatformTenantSession
} from "../src/features/platform-admin/permissions/platformPermissions.js";
import {
  getPlatformAdminMeQueryKey
} from "../src/features/platform-admin/api/platformAdminQueryKeys.js";


test("customer admin tenant is never a platform workspace even with platform-like permissions", () => {
  const session = {
    tenantId: "customer-tenant",
    roleKey: "admin",
    user: {
      id: "customer-admin",
      company: { business_type: "retail" }
    }
  };

  assert.equal(isPlatformTenantSession(session), false);
  assert.equal(
    isPlatformPrincipal({
      roleKey: "admin",
      status: "active",
      permissions: {
        "platform.overview.read": true,
        "billing.read": true
      }
    }),
    true
  );
});

test("platform owner tenant and invited platform members are recognized by tenant identity", () => {
  assert.equal(
    isPlatformTenantSession({
      roleKey: "owner",
      user: { company: { business_type: "platform" } }
    }),
    true
  );
  assert.equal(
    isPlatformTenantSession({
      roleKey: "admin",
      user: { company: { business_type: "platform" } }
    }),
    true
  );
});

test("tenant admin role alone never grants platform /admin access", () => {
  assert.equal(
    isPlatformPrincipal({
      roleKey: "admin",
      status: "active",
      permissions: {
        manage_billing: true,
        manage_users: true
      }
    }),
    false
  );
});

test("verified platform admin principal may enter /admin", () => {
  assert.equal(
    isPlatformPrincipal({
      roleKey: "admin",
      status: "active",
      permissions: {
        "platform.overview.read": true,
        "billing.read": true
      }
    }),
    true
  );
});

test("active platform owner with all permissions may enter /admin", () => {
  assert.equal(
    isPlatformPrincipal({
      roleKey: "owner",
      status: "active",
      permissions: { all: true }
    }),
    true
  );
});

test("inactive platform principal is denied", () => {
  assert.equal(
    isPlatformPrincipal({
      roleKey: "admin",
      status: "inactive",
      permissions: {
        "platform.overview.read": true
      }
    }),
    false
  );
});


test("platform admin identity cache key is isolated per authenticated membership", () => {
  const platformOwnerKey = getPlatformAdminMeQueryKey({
    tenantId: "platform-tenant",
    userId: "owner-user",
    roleKey: "owner"
  });
  const customerAdminKey = getPlatformAdminMeQueryKey({
    tenantId: "customer-tenant",
    userId: "customer-admin",
    roleKey: "admin"
  });

  assert.notDeepEqual(platformOwnerKey, customerAdminKey);
  assert.deepEqual(platformOwnerKey.slice(0, 2), ["platform-admin", "me"]);
});


test("auth session boundaries clear React Query data", () => {
  const authStore = readFileSync(
    new URL("../src/features/auth/store/authStore.js", import.meta.url),
    "utf8"
  );

  assert.match(authStore, /setSession:[\s\S]*queryClient\.clear\(\)/);
  assert.match(authStore, /clearSession:[\s\S]*queryClient\.clear\(\)/);
});


test("platform route guard delegates tenant verification to the backend principal endpoint", () => {
  const guard = readFileSync(
    new URL("../src/features/platform-admin/components/PlatformAdminAccessGuard.jsx", import.meta.url),
    "utf8"
  );
  const context = readFileSync(
    new URL("../src/features/platform-admin/components/AdminContext.jsx", import.meta.url),
    "utf8"
  );

  // Any authenticated token may ask /platform-admin/me; the backend decides
  // whether its TenantUser belongs to the canonical platform tenant.
  assert.doesNotMatch(guard, /isPlatformTenantSession/);
  assert.match(guard, /ADMIN_PREVIEW \|\| isAuthenticated/);
  assert.match(guard, /platformAdminApi\.me/);
  assert.match(guard, /!isPlatformPrincipal\(query\.data\)/);

  assert.doesNotMatch(context, /isPlatformTenantSession/);
  assert.match(context, /ADMIN_PREVIEW \|\| auth\.status === "authenticated"/);
});
