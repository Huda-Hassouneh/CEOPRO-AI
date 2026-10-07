export const PRODUCTION_PLAN_CATALOG_VERSION = "2026-10-v2";

export type ProductionBillingOption = {
  period: string;
  months: number;
  intervalUnit: "month" | "year";
  intervalCount: number;
  discountPercent: number;
};

export type ProductionPlanFeature = {
  code: string;
  limitValue: number | null;
  metadata?: Record<string, unknown>;
};

export type ProductionPlanDefinition = {
  code: "starter" | "growth" | "enterprise";
  name: string;
  name_ar: string;
  tierLevel: number;
  description: string;
  description_ar: string;
  price: number;
  currency: "USD";
  billingIntervalValue: 1;
  billingIntervalUnit: "month";
  trialPeriodValue: number;
  isActive: true;
  billingOptions: readonly ProductionBillingOption[];
  features: readonly ProductionPlanFeature[];
};

const STANDARD_BILLING_OPTIONS = Object.freeze([
  {
    period: "monthly",
    months: 1,
    intervalUnit: "month",
    intervalCount: 1,
    discountPercent: 0,
  },
  {
    period: "three-months",
    months: 3,
    intervalUnit: "month",
    intervalCount: 3,
    discountPercent: 10,
  },
  {
    period: "six-months",
    months: 6,
    intervalUnit: "month",
    intervalCount: 6,
    discountPercent: 20,
  },
] as const satisfies readonly ProductionBillingOption[]);

function booleanFeature(
  code: string,
  metadata?: Record<string, unknown>,
): ProductionPlanFeature {
  return { code, limitValue: null, ...(metadata ? { metadata } : {}) };
}

function limitFeature(
  code: string,
  limitValue: number,
  metadata?: Record<string, unknown>,
): ProductionPlanFeature {
  return { code, limitValue, ...(metadata ? { metadata } : {}) };
}

function competitorMonitoringMetadata(
  monitoringFrequencyMinutes: number,
  monitoringChecksPerMonth: number,
) {
  return {
    source: "production-catalog",
    configuration: {
      monitoringFrequencyMinutes,
      monitoringChecksPerMonth,
      operationalTarget: "data_sources.sync_frequency_minutes",
    },
  };
}

/**
 * Production catalog rationale:
 * - Starter follows the technical specification's "core dashboard analytics,
 *   basic data ingestion, and limited AI-assisted operations".
 * - Growth adds the specification's demand forecasting, competitor intelligence,
 *   advanced analytics, and expanded AI capacity.
 * - Enterprise keeps the same product surface with materially higher workload
 *   limits, more integrations, and faster competitor monitoring.
 *
 * Numeric quotas and prices are commercial product decisions, not values stated
 * in the requirements document. They are intentionally centralized here so
 * production bootstrap, tests, UI, and Stripe all reconcile to one manifest.
 *
 * Provider currency decision (catalog v2): the connected Stripe account is US-
 * based and does not support JOD settlement. Standard plans therefore use USD
 * end-to-end so Plan.currency, Stripe Price currency, fixed-amount promotions,
 * invoices, and price-version history cannot drift across currencies. The clean
 * USD price points preserve approximately the commercial level of the earlier
 * 39/99/249 JOD proposal without introducing an implicit FX layer into standard
 * plan checkout. Local-currency display can be added separately as non-binding
 * presentation if desired.
 */
export const PRODUCTION_PLANS = Object.freeze([
  {
    code: "starter",
    name: "Starter",
    name_ar: "البداية",
    tierLevel: 1,
    description:
      "Core analytics, basic data ingestion, product management, and a practical AI knowledge allowance for small businesses getting started with CEOPRO.",
    description_ar:
      "تحليلات أساسية وتكامل بيانات أساسي وإدارة المنتجات وحصة عملية من مساعد المعرفة بالذكاء الاصطناعي للشركات الصغيرة التي تبدأ باستخدام CEOPRO.",
    price: 55,
    currency: "USD",
    billingIntervalValue: 1,
    billingIntervalUnit: "month",
    trialPeriodValue: 14,
    isActive: true,
    billingOptions: STANDARD_BILLING_OPTIONS,
    features: [
      booleanFeature("dashboard_analytics"),
      booleanFeature("product_management"),
      booleanFeature("data_integration"),
      limitFeature("rag_assistant", 100_000),
      limitFeature("document_extraction", 51_200),
      limitFeature("document_storage_mb", 1_024),
      limitFeature("tracked_products", 250),
      limitFeature("connected_data_sources", 1),
    ],
  },
  {
    code: "growth",
    name: "Growth",
    name_ar: "النمو",
    tierLevel: 2,
    description:
      "Advanced analytics for growing businesses, including demand forecasting, market and competitor intelligence, larger AI capacity, and broader data connectivity.",
    description_ar:
      "تحليلات متقدمة للشركات النامية تشمل التنبؤ بالطلب وذكاء السوق والمنافسين وسعة أكبر للذكاء الاصطناعي وربط مصادر بيانات أكثر.",
    price: 140,
    currency: "USD",
    billingIntervalValue: 1,
    billingIntervalUnit: "month",
    trialPeriodValue: 14,
    isActive: true,
    billingOptions: STANDARD_BILLING_OPTIONS,
    features: [
      booleanFeature("dashboard_analytics"),
      booleanFeature("product_management"),
      booleanFeature("data_integration"),
      booleanFeature("market_intelligence"),
      booleanFeature("demand_prediction"),
      booleanFeature("competitor_management", competitorMonitoringMetadata(1_440, 30)),
      limitFeature("rag_assistant", 500_000),
      limitFeature("document_extraction", 512_000),
      limitFeature("document_storage_mb", 10_240),
      limitFeature("tracked_products", 2_000),
      limitFeature("connected_data_sources", 5),
      limitFeature("tracked_competitors", 10),
      limitFeature("sentiment_analysis", 20_000),
    ],
  },
  {
    code: "enterprise",
    name: "Enterprise",
    name_ar: "المؤسسات",
    tierLevel: 3,
    description:
      "High-capacity CEOPRO access for data-heavy businesses, with advanced integrations, significantly larger AI and document workloads, and faster competitor monitoring.",
    description_ar:
      "وصول عالي السعة إلى CEOPRO للشركات كثيفة البيانات مع تكاملات متقدمة وأحمال أكبر بكثير للذكاء الاصطناعي والمستندات ومراقبة أسرع للمنافسين.",
    price: 350,
    currency: "USD",
    billingIntervalValue: 1,
    billingIntervalUnit: "month",
    trialPeriodValue: 7,
    isActive: true,
    billingOptions: STANDARD_BILLING_OPTIONS,
    features: [
      booleanFeature("dashboard_analytics"),
      booleanFeature("product_management"),
      booleanFeature("data_integration"),
      booleanFeature("market_intelligence"),
      booleanFeature("demand_prediction"),
      booleanFeature("competitor_management", competitorMonitoringMetadata(360, 120)),
      limitFeature("rag_assistant", 2_000_000),
      limitFeature("document_extraction", 2_097_152),
      limitFeature("document_storage_mb", 51_200),
      limitFeature("tracked_products", 10_000),
      limitFeature("connected_data_sources", 20),
      limitFeature("tracked_competitors", 50),
      limitFeature("sentiment_analysis", 100_000),
    ],
  },
] as const satisfies readonly ProductionPlanDefinition[]);

export const PRODUCTION_PLAN_NAMES = Object.freeze(
  PRODUCTION_PLANS.map((plan) => plan.name),
);
