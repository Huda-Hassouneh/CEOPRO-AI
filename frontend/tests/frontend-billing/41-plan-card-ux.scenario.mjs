import test from "node:test";
import assert from "node:assert/strict";
import { read, readJson } from "./_helpers.mjs";

test("41.01 standard plan cards use compact progressive summaries instead of repeating every feature", async () => {
  const card = await read("src/features/billing/components/PlanCard.jsx");
  const selector = await read("src/features/billing/components/PlanSelector.jsx");

  assert.match(card, /compactSummary/);
  assert.match(card, /includesPrevious/);
  assert.match(card, /getCompactFeatureEntries/);
  assert.match(selector, /previousPlan=\{index > 0 \? activePlans\[index - 1\] : null\}/);
  assert.match(selector, /compactSummary/);
});

test("41.02 Custom Plan is a separate callout outside the three-column standard-plan grid", async () => {
  const selector = await read("src/features/billing/components/PlanSelector.jsx");
  const choose = await read("src/features/billing/pages/ChoosePlanPage.jsx");
  const callout = await read("src/features/billing/components/CustomPlanCallout.jsx");

  assert.match(selector, /<CustomPlanCallout/);
  assert.match(choose, /<CustomPlanCallout/);
  assert.match(callout, /ceopro-custom-plan-callout/);
  assert.doesNotMatch(selector, /<PlanCard[\s\S]*?key=["']custom["']/);
});

test("41.03 full comparison is collapsed by default and can be expanded accessibly", async () => {
  const choose = await read("src/features/billing/pages/ChoosePlanPage.jsx");

  assert.match(choose, /useState\(false\)/);
  assert.match(choose, /aria-expanded=\{showComparison\}/);
  assert.match(choose, /aria-controls=["']billing-plan-comparison["']/);
  assert.match(choose, /\{showComparison && \(/);
});

test("41.04 configuration features are shown as configured instead of unlimited", async () => {
  const comparison = await read("src/features/billing/components/PlanComparisonTable.jsx");
  assert.match(comparison, /feature\.type === ["']configuration["']/);
  assert.match(comparison, /billing\.management\.configured/);
});

test("41.05 new compact-plan UX strings exist in English and Arabic", async () => {
  const [en, ar] = await Promise.all([
    readJson("src/assets/locales/en.json"),
    readJson("src/assets/locales/ar.json"),
  ]);

  for (const locale of [en, ar]) {
    assert.ok(locale.billing.plans.highlights);
    assert.ok(locale.billing.plans.includesPrevious);
    assert.ok(locale.billing.plans.custom.calloutTitle);
    assert.ok(locale.billing.management.comparison.show);
    assert.ok(locale.billing.management.comparison.hide);
  }
});
