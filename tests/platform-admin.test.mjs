import assert from "node:assert/strict";
import {
  can,
  PLATFORM_ROLES,
  protectLastOwner,
} from "../src/features/platform-admin/permissions/platformPermissions.js";
import {
  previewAdapter as api,
  setPreviewRole,
} from "../src/features/platform-admin/api/previewAdapter.js";
import { validatePlan } from "../src/features/platform-admin/api/validation.js";
import {
  PREVIEW_PLANS,
  getPreviewPlanPrice,
  replacePreviewPlan,
} from "../src/shared/catalog/planCatalog.js";
import { PREVIEW_PLANS as billingPlans } from "../src/features/billing/config/billingPreviewData.js";
import { en, ar } from "../src/features/platform-admin/locales/messages.js";

assert.deepEqual(Object.keys(en).sort(), Object.keys(ar).sort(), "English / Arabic key parity");
assert.deepEqual(PLATFORM_ROLES, ["owner", "admin"]);
assert.equal(can(null, "companies.read"), false);
assert.equal(can({ roleKey: "owner", role: "owner", status: "inactive", permissions: { all: true } }, "plans.manage"), false);
assert.equal(can({ roleKey: "admin", role: "admin", status: "active", permissions: { all: true } }, "plans.manage"), false, "Only TenantUser owner can enter platform administration");
assert.equal(can({ roleKey: "owner", role: "owner", status: "active", permissions: { all: true } }, "plans.manage"), true);
assert.equal(can({ roleKey: "owner", role: "owner", status: "active", permissions: { "billing.read": true } }, "billing.read"), true);
assert.equal(can({ roleKey: "owner", role: "owner", status: "active", permissions: { "billing.read": true } }, "plans.manage"), false);

setPreviewRole("owner");
const owner = await api.me();
assert.equal(owner.roleKey, "owner");
assert.equal(can(owner, "plans.manage"), true);
assert.equal(can(owner, "billing.pricing.manage"), true);

setPreviewRole("admin");
const admin = await api.me();
assert.equal(admin.roleKey, "admin");
assert.equal(can(admin, "billing.read"), false, "Admin is not the platform owner");
await assert.rejects(api.mutate("plans", "pro", "update", PREVIEW_PLANS.pro), { code: "forbidden" });

const onlyOwner = { id: "a", role: "owner", status: "active" };
assert.throws(
  () => protectLastOwner([onlyOwner, { id: "b", role: "owner", status: "pending" }], onlyOwner, { remove: true }),
  { code: "lastAdmin" },
);
assert.doesNotThrow(() =>
  protectLastOwner([onlyOwner, { id: "b", role: "owner", status: "active" }], onlyOwner, { remove: true }),
);

setPreviewRole("owner");
const original = structuredClone(PREVIEW_PLANS.pro);
assert.equal(billingPlans, PREVIEW_PLANS, "Billing compatibility export shares one catalog");
for (const monthlyPrice of [-1, NaN, Infinity]) {
  assert.throws(() => validatePlan({ ...original, monthlyPrice }), { code: "invalid" });
}
assert.throws(() => validatePlan({ ...original, discounts: { "three-months": 100 } }), { code: "invalid" });
assert.throws(() => validatePlan({ ...original, limits: { products: -1 } }), { code: "invalid" });
assert.doesNotThrow(() => validatePlan({ ...original, limits: { products: null } }));

const updated = await api.mutate("plans", "pro", "update", {
  ...original,
  monthlyPrice: 109,
  discounts: { ...original.discounts, "three-months": 15 },
  limits: { ...original.limits, products: null },
});
assert.equal(updated.monthlyPrice, 109);
assert.equal(getPreviewPlanPrice("pro", "three-months").total, 277.95);
assert.equal(billingPlans.pro.limits.products, null);
await assert.rejects(api.mutate("plans", "pro", "update", original), { code: "conflict" });
replacePreviewPlan(original);

setPreviewRole(null);
await assert.rejects(api.list("overview"), { code: "forbidden" });
console.log("PASS: TenantUser owner authorization, DB-style permissions, owner invariant, plan validation and preview contract.");
