import type { Prisma } from "../../../generated/prisma/client.js";
import { prisma } from "../../../config/database.js";

export interface OnboardingRecord {
  tenantId: string;
  currentStep: number;
  highestCompletedStep: number;
  industry: string | null;
  businessSize: string | null;
  annualRevenue: string | null;
  city: string | null;
  objectives: string[];
  selectedPlan: string | null;
  checkoutMode: string;
  billingPeriod: string;
  customPlan: Prisma.JsonValue;
  sourceStatuses: Prisma.JsonValue;
  websiteUrl: string | null;
  databaseProvider: string | null;
  downloadedTemplates: string[];
  isComplete: boolean;
  countryCode: string;
  preferredLanguage: string;
}

type Transaction = Prisma.TransactionClient;

async function withTenantContext<T>(
  tenantId: string,
  userId: string,
  operation: (tx: Transaction) => Promise<T>
): Promise<T> {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${tenantId}, true),
        set_config('app.current_user_id', ${userId}, true)
    `;
    return operation(tx);
  });
}

async function selectState(tx: Transaction, tenantId: string) {
  const rows = await tx.$queryRaw<OnboardingRecord[]>`
    SELECT
      o.tenant_id AS "tenantId",
      o.current_step AS "currentStep",
      o.highest_completed_step AS "highestCompletedStep",
      o.industry,
      o.business_size AS "businessSize",
      o.annual_revenue AS "annualRevenue",
      o.city,
      o.objectives,
      o.selected_plan AS "selectedPlan",
      o.checkout_mode AS "checkoutMode",
      o.billing_period AS "billingPeriod",
      o.custom_plan AS "customPlan",
      o.source_statuses AS "sourceStatuses",
      o.website_url AS "websiteUrl",
      o.database_provider AS "databaseProvider",
      o.downloaded_templates AS "downloadedTemplates",
      o.is_complete AS "isComplete",
      c.country_code AS "countryCode",
      c.preferred_language AS "preferredLanguage"
    FROM onboarding o
    JOIN companies c ON c.tenant_id = o.tenant_id
    WHERE o.tenant_id = ${tenantId}::uuid
  `;
  const state = rows[0];
  if (!state) throw new Error("Onboarding state was not found after write.");
  return state;
}

export async function ensureState(tenantId: string, userId: string) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.$executeRaw`
      INSERT INTO onboarding (tenant_id)
      VALUES (${tenantId}::uuid)
      ON CONFLICT (tenant_id) DO NOTHING
    `;
    return selectState(tx, tenantId);
  });
}

export async function updateRegion(
  tenantId: string,
  userId: string,
  data: {
    countryCode: string;
    city: string;
    language: string;
    currency: string;
    timezone: string;
  }
) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.company.update({
      where: { id: tenantId },
      data: {
        countryCode: data.countryCode,
        operatingCountries: [data.countryCode],
        primaryCurrency: data.currency,
        supportedCurrencies: [data.currency],
        timezone: data.timezone,
        preferredLanguage: data.language,
        supportedLanguages: [data.language]
      }
    });
    await tx.user.update({
      where: { userId },
      data: { preferredLanguage: data.language }
    });
    await tx.$executeRaw`
      INSERT INTO onboarding (tenant_id, city, current_step, highest_completed_step)
      VALUES (${tenantId}::uuid, ${data.city}, 2, 1)
      ON CONFLICT (tenant_id) DO UPDATE SET
        city = EXCLUDED.city,
        current_step = GREATEST(onboarding.current_step, 2),
        highest_completed_step = GREATEST(onboarding.highest_completed_step, 1),
        updated_at = NOW()
    `;
    return selectState(tx, tenantId);
  });
}

export async function updateProfile(
  tenantId: string,
  userId: string,
  input: {
    industry: string;
    businessSize?: string;
    annualRevenue?: string;
    completedStep: number;
  }
) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.$executeRaw`
      INSERT INTO onboarding (tenant_id)
      VALUES (${tenantId}::uuid)
      ON CONFLICT (tenant_id) DO NOTHING
    `;
    await tx.$executeRaw`
      UPDATE onboarding SET
        industry = ${input.industry},
        business_size = COALESCE(${input.businessSize ?? null}, business_size),
        annual_revenue = COALESCE(${input.annualRevenue ?? null}, annual_revenue),
        current_step = GREATEST(current_step, ${Math.min(6, input.completedStep + 1)}),
        highest_completed_step = GREATEST(highest_completed_step, ${input.completedStep}),
        updated_at = NOW()
      WHERE tenant_id = ${tenantId}::uuid
    `;
    return selectState(tx, tenantId);
  });
}

export async function updateGoals(
  tenantId: string,
  userId: string,
  objectives: string[]
) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.$executeRaw`
      INSERT INTO onboarding (tenant_id)
      VALUES (${tenantId}::uuid)
      ON CONFLICT (tenant_id) DO NOTHING
    `;
    await tx.$executeRaw`
      UPDATE onboarding SET
        objectives = ${objectives},
        current_step = GREATEST(current_step, 5),
        highest_completed_step = GREATEST(highest_completed_step, 4),
        updated_at = NOW()
      WHERE tenant_id = ${tenantId}::uuid
    `;
    return selectState(tx, tenantId);
  });
}

export async function updatePlan(
  tenantId: string,
  userId: string,
  input: {
    selectedPlan: string;
    checkoutMode: string;
    billingPeriod: string;
    customPlan?: Record<string, string | number | boolean>;
  }
) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.$executeRaw`
      INSERT INTO onboarding (tenant_id)
      VALUES (${tenantId}::uuid)
      ON CONFLICT (tenant_id) DO NOTHING
    `;
    const customPlan = input.customPlan ? JSON.stringify(input.customPlan) : null;
    await tx.$executeRaw`
      UPDATE onboarding SET
        selected_plan = ${input.selectedPlan},
        checkout_mode = ${input.checkoutMode},
        billing_period = ${input.billingPeriod},
        custom_plan = COALESCE(${customPlan}::jsonb, custom_plan),
        current_step = 6,
        highest_completed_step = GREATEST(highest_completed_step, 5),
        updated_at = NOW()
      WHERE tenant_id = ${tenantId}::uuid
    `;
    return selectState(tx, tenantId);
  });
}

export async function completeState(
  tenantId: string,
  userId: string,
  input: {
    sourceStatuses: Record<string, { status: string; error: string }>;
    websiteUrl: string;
    databaseProvider: string;
    downloadedTemplates: string[];
  }
) {
  return withTenantContext(tenantId, userId, async (tx) => {
    await tx.$executeRaw`
      UPDATE onboarding SET
        source_statuses = ${JSON.stringify(input.sourceStatuses)}::jsonb,
        website_url = ${input.websiteUrl || null},
        database_provider = ${input.databaseProvider || null},
        downloaded_templates = ${input.downloadedTemplates},
        current_step = 6,
        highest_completed_step = 6,
        is_complete = TRUE,
        completed_at = NOW(),
        updated_at = NOW()
      WHERE tenant_id = ${tenantId}::uuid
    `;
    return selectState(tx, tenantId);
  });
}
