import assert from "node:assert/strict";
import test from "node:test";
import { prisma } from "../../src/config/database.js";
import {
  ensureState,
  updateRegion
} from "../../src/modules/onboarding/repo/onboarding.repo.js";

const tenantId = "22222222-2222-4222-8222-222222222222";
const userId = "11111111-1111-4111-8111-111111111111";

function mockTransaction(t: any) {
  const original = prisma.$transaction;
  const contextValues: unknown[][] = [];
  const writes: Array<{ sql: string; values: unknown[] }> = [];
  const companyUpdates: unknown[] = [];
  const userUpdates: unknown[] = [];
  const state = {
    tenantId,
    currentStep: 1,
    highestCompletedStep: 0,
    industry: null,
    businessSize: null,
    annualRevenue: null,
    city: null,
    objectives: [],
    selectedPlan: null,
    checkoutMode: "trial",
    billingPeriod: "monthly",
    customPlan: {},
    sourceStatuses: {},
    websiteUrl: null,
    databaseProvider: null,
    downloadedTemplates: [],
    isComplete: false,
    countryCode: "JO",
    preferredLanguage: "en"
  };
  const tx = {
    $queryRaw: async (parts: TemplateStringsArray, ...values: unknown[]) => {
      const sql = parts.join("?");
      if (sql.includes("set_config")) contextValues.push(values);
      if (sql.includes('o.tenant_id AS "tenantId"')) return [state];
      return [];
    },
    $executeRaw: async (parts: TemplateStringsArray, ...values: unknown[]) => {
      writes.push({ sql: parts.join("?"), values });
      return 1;
    },
    company: {
      update: async (args: unknown) => companyUpdates.push(args)
    },
    user: {
      update: async (args: unknown) => userUpdates.push(args)
    }
  };
  (prisma as any).$transaction = async (operation: (arg: unknown) => unknown) =>
    operation(tx);
  t.after(() => {
    (prisma as any).$transaction = original;
  });
  return { contextValues, writes, companyUpdates, userUpdates };
}

test("reading onboarding state creates the row inside verified tenant RLS context", async (t) => {
  const mock = mockTransaction(t);
  const state = await ensureState(tenantId, userId);

  assert.equal(state.tenantId, tenantId);
  assert.ok(mock.contextValues.some((values) => values.includes(tenantId)));
  assert.ok(mock.contextValues.some((values) => values.includes(userId)));
  assert.ok(mock.writes.some(({ sql }) => sql.includes("INSERT INTO onboarding")));
});

test("regional preferences update company, user, and onboarding in one tenant transaction", async (t) => {
  const mock = mockTransaction(t);
  const state = await updateRegion(tenantId, userId, {
    countryCode: "JO",
    city: "Amman",
    language: "ar",
    currency: "JOD",
    timezone: "Asia/Amman"
  });

  assert.equal(state.tenantId, tenantId);
  assert.equal(mock.companyUpdates.length, 1);
  assert.equal(mock.userUpdates.length, 1);
  assert.deepEqual(mock.companyUpdates[0], {
    where: { id: tenantId },
    data: {
      countryCode: "JO",
      operatingCountries: ["JO"],
      primaryCurrency: "JOD",
      supportedCurrencies: ["JOD"],
      timezone: "Asia/Amman",
      preferredLanguage: "ar",
      supportedLanguages: ["ar"]
    }
  });
  assert.deepEqual(mock.userUpdates[0], {
    where: { userId },
    data: { preferredLanguage: "ar" }
  });
  assert.ok(mock.contextValues.some((values) => values.includes(tenantId)));
  assert.ok(mock.contextValues.some((values) => values.includes(userId)));
  assert.ok(mock.writes.some(({ sql }) => sql.includes("INSERT INTO onboarding")));
});
