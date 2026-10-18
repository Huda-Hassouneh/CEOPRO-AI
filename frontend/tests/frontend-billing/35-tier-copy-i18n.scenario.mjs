import test from 'node:test';
import assert from 'node:assert/strict';
import { read, readJson } from './_helpers.mjs';

const loadLocales = async () => ({
  en: await readJson('src/assets/locales/en.json'),
  ar: await readJson('src/assets/locales/ar.json'),
});

const getBilling = (locale) => locale.billing;

for (const localeKey of ['en', 'ar']) {
  test(`35.01 ${localeKey} billing copy defines Starter, Growth and Enterprise`, async () => {
    const locales = await loadLocales();
    const plans = getBilling(locales[localeKey]).plans;
    assert.ok(plans.starter, 'Missing billing.plans.starter');
    assert.ok(plans.growth, 'Missing billing.plans.growth');
    assert.ok(plans.enterprise, 'Missing billing.plans.enterprise');
    assert.ok(plans.custom, 'Custom Plan copy must remain available');
  });
}

test('35.02 customer billing copy no longer describes the old Standard/Pro two-tier catalog', async () => {
  const { en, ar } = await loadLocales();
  const fields = [
    en.billing.choose?.subtitle,
    en.billing.trial?.title,
    en.billing.trial?.description,
    en.billing.management?.reviewSubscription,
    en.billing.recommendation?.title,
    en.billing.recommendation?.description,
    ar.billing.choose?.subtitle,
    ar.billing.trial?.title,
    ar.billing.trial?.description,
    ar.billing.management?.reviewSubscription,
    ar.billing.recommendation?.title,
    ar.billing.recommendation?.description,
  ].filter(Boolean).join('\n');

  assert.doesNotMatch(fields, /\bStandard\b|\bPro\b/i);
  assert.doesNotMatch(
    String(en.billing.choose?.subtitle || ''),
    /same AI models and features/i,
    'Tier copy must not claim all plans have the same features; Growth/Enterprise intentionally add capabilities.'
  );
});

test('35.03 RAG customer-facing quota copy is token-based rather than query/question-based', async () => {
  const { en } = await loadLocales();
  const ragCopy = [
    en.billing.management?.usageLabels?.rag_assistant,
    en.billing.management?.context?.rag_assistant?.title,
    en.billing.management?.context?.rag_assistant?.description,
    en.billing.features?.ragQueries,
  ].filter(Boolean).join('\n');

  assert.match(ragCopy, /token/i);
  assert.doesNotMatch(ragCopy, /quer(?:y|ies)|question/i);
});

test('35.04 boolean plan features render as included capabilities, not unlimited numeric quotas', async () => {
  const card = await read('src/features/billing/components/PlanCard.jsx');
  const summary = await read('src/features/billing/components/PlanSummaryCard.jsx');
  const comparison = await read('src/features/billing/components/PlanComparisonTable.jsx');

  assert.match(card, /feature\?\.type === ['"]boolean['"]/);
  assert.match(summary, /feature\?\.type === ['"]boolean['"]/);
  assert.match(comparison, /feature\.type === ["']boolean["']/);
  assert.match(summary, /billing\.management\.included/);
  assert.match(comparison, /billing\.management\.included/);
});

test('35.05 usage recommendations use production entitlement codes and the canonical trialing status', async () => {
  const source = await read('src/features/billing/utils/subscriptionRecommendations.js');
  for (const code of ['tracked_products', 'tracked_competitors', 'rag_assistant', 'document_storage_mb']) {
    assert.match(source, new RegExp(code));
  }
  assert.match(source, /subscription\.status === ["']trialing["']/);
  assert.doesNotMatch(source, /subscription\.status === ["']trial["']/);
});
