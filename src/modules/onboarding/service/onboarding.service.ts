import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { ServiceResult } from "../../../types/service.js";
import type {
  CompleteOnboardingInput,
  GoalsInput,
  PlanInput,
  ProfileInput,
  RegionalPreferencesInput
} from "../types/onboarding.dto.js";
import * as repo from "../repo/onboarding.repo.js";

const currencies: Record<string, string> = {
  BE: "EUR", FR: "EUR", LU: "EUR", MD: "MDL", PL: "PLN", RO: "RON",
  SK: "EUR", ES: "EUR", BW: "BWP", BF: "XOF", CM: "XAF", CF: "XAF",
  CI: "XOF", CD: "CDF", EG: "EGP", GN: "GNF", GW: "XOF", JO: "JOD",
  LR: "LRD", ML: "XOF", MA: "MAD", SN: "XOF", SL: "SLE", TN: "TND"
};

const timezones: Record<string, string> = {
  BE: "Europe/Brussels", FR: "Europe/Paris", LU: "Europe/Luxembourg",
  MD: "Europe/Chisinau", PL: "Europe/Warsaw", RO: "Europe/Bucharest",
  SK: "Europe/Bratislava", ES: "Europe/Madrid", BW: "Africa/Gaborone",
  BF: "Africa/Ouagadougou", CM: "Africa/Douala", CF: "Africa/Bangui",
  CI: "Africa/Abidjan", CD: "Africa/Kinshasa", EG: "Africa/Cairo",
  GN: "Africa/Conakry", GW: "Africa/Bissau", JO: "Asia/Amman",
  LR: "Africa/Monrovia", ML: "Africa/Bamako", MA: "Africa/Casablanca",
  SN: "Africa/Dakar", SL: "Africa/Freetown", TN: "Africa/Tunis"
};

type OnboardingState = ReturnType<typeof toState>;
type OnboardingResult = ServiceResult<{ state: OnboardingState }>;

const incomplete: OnboardingResult = {
  success: false,
  code: ERROR_CODES.ONBOARDING_INCOMPLETE
};

function ok(record: repo.OnboardingRecord, message: string): OnboardingResult {
  return { success: true, data: { state: toState(record) }, message };
}

function toState(record: repo.OnboardingRecord) {
  return {
    currentStep: record.currentStep,
    highestCompletedStep: record.highestCompletedStep,
    industry: record.industry ?? "",
    businessSize: record.businessSize ?? "",
    annualRevenue: record.annualRevenue ?? "1m-10m",
    country: record.countryCode,
    city: record.city ?? "",
    language: record.preferredLanguage,
    objectives: record.objectives,
    selectedPlan: record.selectedPlan ?? "",
    checkoutMode: record.checkoutMode,
    billingPeriod: record.billingPeriod,
    customPlan: record.customPlan,
    step5Completed: record.highestCompletedStep >= 5,
    sourceStatuses: record.sourceStatuses,
    websiteUrl: record.websiteUrl ?? "",
    databaseProvider: record.databaseProvider ?? "",
    downloadedTemplates: record.downloadedTemplates,
    isComplete: record.isComplete
  };
}

export async function getState(tenantId: string): Promise<OnboardingResult> {
  const state = await repo.ensureState(tenantId);
  return ok(state, "Onboarding state retrieved successfully");
}

export async function saveRegion(tenantId: string, userId: string, input: RegionalPreferencesInput): Promise<OnboardingResult> {
  const state = await repo.updateRegion(tenantId, userId, {
    countryCode: input.country,
    city: input.city,
    language: input.language,
    currency: currencies[input.country],
    timezone: timezones[input.country]
  });
  return ok(state, "Regional preferences saved successfully");
}

export async function saveProfile(tenantId: string, input: ProfileInput): Promise<OnboardingResult> {
  const existing = await repo.ensureState(tenantId);
  if (existing.highestCompletedStep < input.completedStep - 1) return incomplete;
  const state = await repo.updateProfile(tenantId, input);
  return ok(state, "Business profile saved successfully");
}

export async function saveGoals(tenantId: string, input: GoalsInput): Promise<OnboardingResult> {
  const existing = await repo.ensureState(tenantId);
  if (existing.highestCompletedStep < 3) return incomplete;
  const state = await repo.updateGoals(tenantId, [...new Set(input.objectives)]);
  return ok(state, "Strategic goals saved successfully");
}

export async function savePlan(tenantId: string, input: PlanInput): Promise<OnboardingResult> {
  const existing = await repo.ensureState(tenantId);
  if (existing.highestCompletedStep < 4) return incomplete;
  const state = await repo.updatePlan(tenantId, input);
  return ok(state, "Plan selection saved successfully");
}

export async function complete(tenantId: string, input: CompleteOnboardingInput): Promise<OnboardingResult> {
  const existing = await repo.ensureState(tenantId);
  if (existing.highestCompletedStep < 5) return incomplete;
  const state = await repo.completeState(tenantId, input);
  return ok(state, "Onboarding completed successfully");
}
