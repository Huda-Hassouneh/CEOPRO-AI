import { test } from "@playwright/test";

type BlockedCase = {
  title: string;
  category: string;
  component: string;
  expected: string;
  actual: string;
  prerequisite: string;
};

const cases: BlockedCase[] = [
  {
    title: "render tenant-specific recommendations from live customer data",
    category: "RECOMMENDATION_FRONTEND_INTEGRATION_MISSING",
    component: "frontend dashboard / Node API",
    expected: "A recommendation list sourced from the authenticated tenant API.",
    actual: "DashboardHomePage does not render the static RecommendationCard and has no business-recommendations API client.",
    prerequisite: "Implement the customer-facing Node API and wire a real frontend page/card to it."
  },
  {
    title: "deny Starter, Growth, Enterprise, missing, expired, and suspended grants",
    category: "RECOMMENDATION_ENTITLEMENT_BYPASS",
    component: "Node feature/subscription authorization",
    expected: "Deny recommendation reads unless an active subscription explicitly grants business_recommendations.",
    actual: "No customer recommendation route or entitlement check exists. AI JWT authentication alone does not enforce subscription access.",
    prerequisite: "Define the customer exposure policy and add a Node entitlement-gated endpoint."
  },
  {
    title: "allow explicitly enabled custom plans and reject disabled custom plans",
    category: "RECOMMENDATION_NODE_INTEGRATION_MISSING",
    component: "Node custom-plan entitlement flow",
    expected: "Custom plan feature grant controls the customer recommendation endpoint.",
    actual: "The feature catalog can represent the boolean grant, but there is no recommendation route consuming it.",
    prerequisite: "Connect the implemented central entitlement service to the new endpoint."
  },
  {
    title: "prevent subscription changes from racing with an in-flight recommendation request",
    category: "RECOMMENDATION_NODE_INTEGRATION_MISSING",
    component: "Node subscription and request lifecycle",
    expected: "Access is checked under the documented subscription policy for the request lifetime.",
    actual: "No Node recommendation request lifecycle exists.",
    prerequisite: "Specify subscription-change semantics and implement the gated API before concurrency testing."
  },
  {
    title: "display product, category, priority, and evidence from the AI response",
    category: "RECOMMENDATION_EVIDENCE_MISSING",
    component: "AI response contract / frontend",
    expected: "Only evidence present in the API response is displayed and linked.",
    actual: "AI response currently exposes product_id, category, priority, and message only; it has no evidence records or stable recommendation ID.",
    prerequisite: "Agree on an evidence-bearing response contract and expose it through Node/UI."
  },
  {
    title: "render loading, empty, partial-data, stale-data, and AI failure states",
    category: "RECOMMENDATION_FALSE_SUCCESS_UI",
    component: "frontend recommendation page",
    expected: "Real endpoint state is shown without preview data being mistaken for a result.",
    actual: "No customer-facing recommendation page is connected to the AI endpoint.",
    prerequisite: "Implement frontend states against the production Node response contract."
  },
  {
    title: "keep Arabic recommendations translated and aligned right-to-left",
    category: "FRONTEND_LOCALIZATION_ERROR",
    component: "frontend recommendation presentation",
    expected: "Arabic labels and structured recommendation content render in RTL.",
    actual: "Existing dashboard recommendation content is static sample copy; no live localized recommendation view exists.",
    prerequisite: "Implement a localized view and structured translation-safe API fields."
  },
  {
    title: "keep English recommendations and category labels tied to actual signals",
    category: "RECOMMENDATION_FRONTEND_INTEGRATION_MISSING",
    component: "frontend recommendation presentation",
    expected: "Rendered copy reflects a real recommendation response and its category.",
    actual: "The legacy card displays hard-coded translated sample headline and description.",
    prerequisite: "Replace static card usage with the real response after the Node contract is defined."
  },
  {
    title: "tenant A cannot query or infer tenant B products or recommendations",
    category: "RECOMMENDATION_TENANT_ISOLATION_FAILURE",
    component: "Node API / AI PostgreSQL RLS",
    expected: "Each user receives only tenant-owned products and signal evidence.",
    actual: "AI database code uses tenant-scoped RLS context; customer Node path and paired safe browser tenants are not configured.",
    prerequisite: "Configure two dedicated tenants, a restricted non-BYPASSRLS role, and a real Node endpoint."
  },
  {
    title: "exclude unpaid and cancelled invoices and future-dated records from sales signals",
    category: "RECOMMENDATION_SALES_CALCULATION_ERROR",
    component: "AI insights/pipeline.py",
    expected: "Sales windows include only contract-approved completed sales within the window.",
    actual: "The current sales query uses issue_date lower bounds only and does not filter payment_status or exclude future dates.",
    prerequisite: "Agree the valid-sale policy and add a safe AI PostgreSQL regression run."
  },
  {
    title: "avoid comparing JOD product prices with USD competitor observations",
    category: "RECOMMENDATION_CURRENCY_MISMATCH",
    component: "AI insights/pipeline.py price-gap query",
    expected: "Compare only same-currency values or use approved FX normalization.",
    actual: "Current query averages latest prices by mapping without matching currencies.",
    prerequisite: "Define comparable-currency/FX behavior and run against controlled observations."
  },
  {
    title: "ignore inactive mappings, untracked competitors, and unavailable price observations",
    category: "RECOMMENDATION_PRODUCT_MAPPING_ERROR",
    component: "AI insights/pipeline.py price-gap query",
    expected: "Only active, tracked, available mapped observations contribute.",
    actual: "Current query does not filter mapping/tracking/availability state.",
    prerequisite: "Add the eligibility filters and verify the query with the dedicated test database."
  },
  {
    title: "exclude expired forecasts and report an insufficient-data state",
    category: "RECOMMENDATION_FORECAST_ERROR",
    component: "AI insights/pipeline.py forecast loader",
    expected: "Do not treat expired forecast rows as current demand evidence.",
    actual: "Current loader picks the latest-created row and checks only target-vs-created horizon, not whether the target is still current.",
    prerequisite: "Define forecast validity and test current/expired/incomplete rows in the safe DB."
  },
  {
    title: "show that uploaded transactions affect recommendations under the agreed sales contract",
    category: "SALES_SOURCE_CONTRACT_MISMATCH",
    component: "AI sales source / Data Connections producer",
    expected: "Recommendations account for canonical imported sales without double-counting invoices.",
    actual: "AI recommendations read invoices and invoice_items; the ingestion worker writes transactions. No reconciliation contract exists.",
    prerequisite: "Choose the canonical source and deduplication contract before connecting both tables."
  },
  {
    title: "do not claim competitor price changes caused sales changes",
    category: "RECOMMENDATION_FALSE_CAUSALITY",
    component: "AI causal_chain.py / presentation",
    expected: "Describe event timing as possible correlation, including uncertainty.",
    actual: "Current AI detector hedges the message; browser presentation is not integrated for verification.",
    prerequisite: "Expose structured event evidence and preserve hedged wording through Node/UI."
  },
  {
    title: "persist, dismiss, acknowledge, or evaluate recommendation outcomes only when supported",
    category: "RECOMMENDATION_OUTCOME_TRACKING_UNAVAILABLE",
    component: "recommendation lifecycle / database ownership",
    expected: "Only implemented lifecycle actions are shown and persisted under a defined owner.",
    actual: "AI generates recommendations on demand; the wrapper does not persist them, and recommendation_outcomes is owned by forecast evidence workflows.",
    prerequisite: "Decide recommendation identity, lifecycle, retention, and table ownership."
  },
  {
    title: "complete the actual frontend to Node to AI to PostgreSQL workflow",
    category: "RECOMMENDATION_NODE_INTEGRATION_MISSING",
    component: "frontend → Node → AI → PostgreSQL",
    expected: "The customer request is authorized, scoped, computed, validated, and rendered end to end.",
    actual: "Only the AI JWT-protected API and tenant-scoped signal pipeline exist; Node/frontend customer integration is absent.",
    prerequisite: "Finalize product exposure/entitlement policy, implement Node and frontend contracts, and configure the isolated E2E stack."
  }
];

for (const scenario of cases) {
  test(`Business Recommendations > ${scenario.title}`, async ({}, testInfo) => {
    testInfo.annotations.push({ type: "mode", description: "business-recommendations-blocked-integration" });
    testInfo.annotations.push({ type: "failure-category", description: scenario.category });
    testInfo.annotations.push({ type: "component", description: scenario.component });
    testInfo.annotations.push({ type: "expected-result", description: scenario.expected });
    testInfo.annotations.push({ type: "actual-result", description: scenario.actual });
    testInfo.annotations.push({ type: "prerequisite", description: scenario.prerequisite });
    testInfo.annotations.push({
      type: "diagnostic",
      description: JSON.stringify({ tenantId: null, role: "owner", plan: null, entitlement: "not configured", productId: null, expected: scenario.expected, actual: scenario.actual })
    });
    test.skip(true, `BLOCKED: ${scenario.prerequisite}`);
  });
}
