import { readFile } from 'node:fs/promises';

export const rootUrl = new URL('../../', import.meta.url);
export const read = (path) => readFile(new URL(path, rootUrl), 'utf8');
export const readJson = async (path) => JSON.parse(await read(path));

export const customerBillingFiles = [
  'src/features/billing/pages/ChoosePlanPage.jsx',
  'src/features/billing/pages/BillingCheckoutPage.jsx',
  'src/features/billing/pages/BillingCustomPlanPage.jsx',
  'src/features/billing/pages/CustomPlanOfferPage.jsx',
  'src/features/billing/components/PlanSelector.jsx',
  'src/features/billing/components/PlanCard.jsx',
  'src/features/billing/components/PlanSummaryCard.jsx',
  'src/features/billing/hooks/useCheckout.js',
  'src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx',
  'src/features/onboarding/pages/OnboardingCustomPlanPage.jsx',
  'src/features/onboarding/pages/OnboardingPaymentPage.jsx',
  'src/features/onboarding/pages/OnboardingSubscriptionSuccessPage.jsx',
];

export const readMany = async (paths) =>
  (await Promise.all(paths.map((path) => read(path)))).join('\n');
