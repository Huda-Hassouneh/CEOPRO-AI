import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const seed = fs.readFileSync(path.join(root, "prisma", "seed.ts"), "utf8");
const stripeBootstrap = fs.readFileSync(path.join(root, "prisma", "bootstrap", "stripe.ts"), "utf8");

test("33.01 development seed remains visibly non-production and contains the synthetic showcase plan", () => {
  assert.match(seed, /Development Showcase/);
  assert.match(seed, /Synthetic integration fixture/);
});

test("33.02 production bootstrap commands must never call prisma:seed", () => {
  for (const [name, value] of Object.entries(pkg.scripts ?? {})) {
    if (!/^bootstrap:/.test(name)) continue;
    assert.doesNotMatch(String(value), /prisma:seed|prisma\/seed\.ts/, `${name} must not invoke development seed data`);
  }
});

test("33.03 shared Stripe bootstrap is only a Stripe product bootstrap, not a hidden tenant/data seed", () => {
  assert.match(stripeBootstrap, /onBoardingService/);
  assert.doesNotMatch(stripeBootstrap, /prisma\.seed|Development Showcase|company\.create|user\.create/);
});

test("33.04 a dedicated idempotent production standard-plan bootstrap must exist before release", () => {
  const script = pkg.scripts?.["bootstrap:plans"];
  assert.ok(
    script,
    "Missing package script 'bootstrap:plans'. Current repo can bootstrap the shared Stripe product, but it has no dedicated production standard-plan catalog bootstrap yet.",
  );
  assert.doesNotMatch(String(script), /prisma:seed/, "bootstrap:plans must not use the development seed");
});

test("33.05 final production catalog manifest is explicit rather than inferred from test fixtures", () => {
  const candidates = [
    "prisma/bootstrap/production-plans.ts",
    "prisma/bootstrap/production-plans.json",
    "config/production-plans.ts",
    "src/config/production-plans.ts",
  ];
  const existing = candidates.find((candidate) => fs.existsSync(path.join(root, candidate)));
  assert.ok(
    existing,
    "No explicit production-plan catalog manifest/configuration was found. Do not infer real plan names/prices/features from prisma/seed.ts or automated test fixtures.",
  );
});


test("33.06 production manifest uses the requirements-aligned tier names", () => {
  const manifest = fs.readFileSync(path.join(root, "src", "config", "production-plans.ts"), "utf8");
  assert.match(manifest, /name:\s*"Starter"/);
  assert.match(manifest, /name:\s*"Growth"/);
  assert.match(manifest, /name:\s*"Enterprise"/);
  assert.doesNotMatch(manifest, /name:\s*"Basic"|name:\s*"Pro"/);
});

test("33.07 production bootstrap has dry-run, verification, and live-write safety gates", () => {
  const bootstrap = fs.readFileSync(path.join(root, "prisma", "bootstrap", "production-plans.ts"), "utf8");
  assert.match(String(pkg.scripts?.["bootstrap:plans:dry-run"]), /--dry-run/);
  assert.match(String(pkg.scripts?.["verify:plans:production"]), /--verify-only/);
  assert.match(bootstrap, /CONFIRM_PRODUCTION_PLAN_BOOTSTRAP/);
  assert.match(bootstrap, /CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP/);
  assert.match(bootstrap, /ALLOW_ACTIVE_STANDARD_PLAN_ENTITLEMENT_CHANGES/);
});

test("33.08 production plan bootstrap never creates tenants or users", () => {
  const bootstrap = fs.readFileSync(path.join(root, "prisma", "bootstrap", "production-plans.ts"), "utf8");
  assert.doesNotMatch(bootstrap, /company\.create|user\.create|prisma:seed|Development Showcase/);
});


test("33.09 shared Stripe bootstrap also refuses accidental live/production creation", () => {
  assert.match(stripeBootstrap, /CONFIRM_LIVE_STRIPE_BOOTSTRAP/);
  assert.match(stripeBootstrap, /CONFIRM_PRODUCTION_STRIPE_BOOTSTRAP/);
});

test("33.10 production standard plans use the supported provider currency consistently", () => {
  const manifest = fs.readFileSync(path.join(root, "src", "config", "production-plans.ts"), "utf8");
  assert.match(manifest, /currency:\s*"USD"/);
  assert.doesNotMatch(manifest, /currency:\s*"JOD"/);
  assert.match(manifest, /price:\s*55,/);
  assert.match(manifest, /price:\s*140,/);
  assert.match(manifest, /price:\s*350,/);
});
