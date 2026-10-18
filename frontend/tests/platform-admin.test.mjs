import assert from "node:assert/strict";

import {
  can,
  PLATFORM_ROLES,
  INVITABLE_PLATFORM_ROLES
} from "../src/features/platform-admin/permissions/platformPermissions.js";

import {
  previewAdapter as api,
  setPreviewRole
} from "../src/features/platform-admin/api/previewAdapter.js";

import { validatePlan } from "../src/features/platform-admin/api/validation.js";

import {
  PREVIEW_PLANS,
  getPreviewPlanPrice,
  replacePreviewPlan
} from "../src/shared/catalog/planCatalog.js";

import { PREVIEW_PLANS as billingPlans } from "../src/features/billing/config/billingPreviewData.js";

import { en, ar } from "../src/features/platform-admin/locales/messages.js";

// -----------------------------------------------------------------------------
// TRANSLATION PARITY
// -----------------------------------------------------------------------------

assert.deepEqual(
  Object.keys(en).sort(),
  Object.keys(ar).sort(),
  "English / Arabic key parity"
);

// -----------------------------------------------------------------------------
// PLATFORM ROLES
// -----------------------------------------------------------------------------

assert.deepEqual(
  PLATFORM_ROLES,
  ["owner", "admin", "manager", "accountant", "staff"],
  "All supported platform roles should be available"
);

assert.deepEqual(
  INVITABLE_PLATFORM_ROLES,
  ["admin", "manager", "accountant", "staff"],
  "Owner must never be assignable through Admin Team"
);

// -----------------------------------------------------------------------------
// PERMISSION ENGINE
// -----------------------------------------------------------------------------

assert.equal(
  can(null, "companies.read"),
  false,
  "Missing principal must never be authorized"
);

assert.equal(
  can(
    {
      roleKey: "owner",
      role: "owner",
      status: "inactive",
      permissions: {
        all: true
      }
    },
    "billing.pricing.manage"
  ),
  false,
  "Inactive owner must not retain platform access"
);

assert.equal(
  can(
    {
      roleKey: "admin",
      role: "admin",
      status: "active",
      permissions: {
        "billing.read": true
      }
    },
    "billing.read"
  ),
  true,
  "Platform admin can use permissions assigned by the backend"
);

assert.equal(
  can(
    {
      roleKey: "admin",
      role: "admin",
      status: "active",
      permissions: {
        "billing.read": true
      }
    },
    "billing.pricing.manage"
  ),
  false,
  "Platform admin cannot use permissions that were not assigned"
);

assert.equal(
  can(
    {
      roleKey: "owner",
      role: "owner",
      status: "active",
      permissions: {
        all: true
      }
    },
    "billing.pricing.manage"
  ),
  true,
  "Platform owner has unrestricted permissions"
);

assert.equal(
  can(
    {
      roleKey: "staff",
      role: "staff",
      status: "inactive",
      permissions: {
        "companies.read": true
      }
    },
    "companies.read"
  ),
  false,
  "Inactive platform members cannot use their permissions"
);

// Important:
//
// Role name itself should NOT magically grant permissions.
// Authorization comes from the permissions object.
assert.equal(
  can(
    {
      roleKey: "owner",
      role: "owner",
      status: "active",
      permissions: {
        "billing.read": true
      }
    },
    "billing.read"
  ),
  true
);

assert.equal(
  can(
    {
      roleKey: "owner",
      role: "owner",
      status: "active",
      permissions: {
        "billing.read": true
      }
    },
    "billing.pricing.manage"
  ),
  false,
  "Permissions, not the role string itself, are authoritative"
);

// -----------------------------------------------------------------------------
// PREVIEW OWNER
// -----------------------------------------------------------------------------

setPreviewRole("owner");

const owner = await api.me();

assert.equal(owner.roleKey, "owner");

assert.equal(
  can(owner, "billing.pricing.manage"),
  true,
  "Preview owner must have pricing-management permission"
);

assert.equal(
  can(owner, "adminTeam.invite"),
  true,
  "Preview owner must have Admin Team permissions"
);

// -----------------------------------------------------------------------------
// PREVIEW ADMIN
// -----------------------------------------------------------------------------

setPreviewRole("admin");

const admin = await api.me();

assert.equal(admin.roleKey, "admin");

assert.equal(
  can(admin, "billing.read"),
  true,
  "Admin should have billing read access"
);

assert.equal(
  can(admin, "billing.manage"),
  true,
  "Admin should have billing management access"
);

assert.equal(
  can(admin, "billing.pricing.manage"),
  false,
  "Admin must not manage platform pricing"
);

assert.equal(
  can(admin, "adminTeam.read"),
  true,
  "Admin should be able to read Admin Team"
);

assert.equal(
  can(admin, "adminTeam.roles.manage"),
  false,
  "Admin must not manage platform roles"
);

// Admin must not edit pricing.
await assert.rejects(api.mutate("plans", "pro", "update", PREVIEW_PLANS.pro), {
  code: "forbidden"
});

// -----------------------------------------------------------------------------
// MANAGER
// -----------------------------------------------------------------------------

setPreviewRole("manager");

const manager = await api.me();

assert.equal(can(manager, "companies.read"), true);

assert.equal(can(manager, "users.read"), true);

assert.equal(can(manager, "billing.manage"), false);

assert.equal(can(manager, "adminTeam.read"), false);

// -----------------------------------------------------------------------------
// ACCOUNTANT
// -----------------------------------------------------------------------------

setPreviewRole("accountant");

const accountant = await api.me();

assert.equal(can(accountant, "billing.read"), true);

assert.equal(can(accountant, "billing.manage"), true);

assert.equal(can(accountant, "companies.update"), false);

assert.equal(can(accountant, "adminTeam.read"), false);

// -----------------------------------------------------------------------------
// STAFF
// -----------------------------------------------------------------------------

setPreviewRole("staff");

const staff = await api.me();

assert.equal(can(staff, "companies.read"), true);

assert.equal(can(staff, "users.read"), true);

assert.equal(can(staff, "billing.manage"), false);

assert.equal(can(staff, "adminTeam.read"), false);

// -----------------------------------------------------------------------------
// OWNER CANNOT BE ASSIGNED THROUGH ADMIN TEAM
// -----------------------------------------------------------------------------

setPreviewRole("owner");

await assert.rejects(
  api.mutate("admin-team", null, "invite", {
    email: "forbidden-owner@example.com",
    role: "owner"
  }),
  {
    code: "invalid"
  }
);

// Valid non-owner role should still be accepted.
const invitation = await api.mutate("admin-team", null, "invite", {
  email: "new-admin@example.com",
  role: "admin"
});

assert.equal(invitation.role, "admin");

assert.equal(invitation.status, "pending");

// -----------------------------------------------------------------------------
// PLAN VALIDATION
// -----------------------------------------------------------------------------

setPreviewRole("owner");

const original = structuredClone(PREVIEW_PLANS.pro);

assert.equal(
  billingPlans,
  PREVIEW_PLANS,
  "Billing compatibility export shares one catalog"
);

for (const monthlyPrice of [-1, NaN, Infinity]) {
  assert.throws(
    () =>
      validatePlan({
        ...original,
        monthlyPrice
      }),
    {
      code: "invalid"
    }
  );
}

assert.throws(
  () =>
    validatePlan({
      ...original,
      discounts: {
        "three-months": 100
      }
    }),
  {
    code: "invalid"
  }
);

assert.throws(
  () =>
    validatePlan({
      ...original,
      limits: {
        products: -1
      }
    }),
  {
    code: "invalid"
  }
);

assert.doesNotThrow(() =>
  validatePlan({
    ...original,
    limits: {
      products: null
    }
  })
);

// -----------------------------------------------------------------------------
// OWNER CAN UPDATE PRICING
// -----------------------------------------------------------------------------

const updated = await api.mutate("plans", "pro", "update", {
  ...original,
  monthlyPrice: 109,
  discounts: {
    ...original.discounts,
    "three-months": 15
  },
  limits: {
    ...original.limits,
    products: null
  }
});

assert.equal(updated.monthlyPrice, 109);

assert.equal(getPreviewPlanPrice("pro", "three-months").total, 277.95);

assert.equal(billingPlans.pro.limits.products, null);

// Old version should now produce conflict.
await assert.rejects(api.mutate("plans", "pro", "update", original), {
  code: "conflict"
});

// Restore catalog.
replacePreviewPlan(original);

// -----------------------------------------------------------------------------
// UNAUTHENTICATED ACCESS
// -----------------------------------------------------------------------------

setPreviewRole(null);

await assert.rejects(api.list("overview"), {
  code: "forbidden"
});

// -----------------------------------------------------------------------------
// SUCCESS
// -----------------------------------------------------------------------------

console.log(
  "PASS: platform RBAC, role permissions, protected owner assignment, plan validation and preview contract."
);
