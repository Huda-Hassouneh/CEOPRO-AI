import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getOnboardingPathForStep} from '../src/features/onboarding/config/onboardingSteps.js';
const read=p=>readFileSync(new URL('../src/'+p,import.meta.url),'utf8');
test('original onboarding route progression and historical Custom route are retained',()=>{
 assert.deepEqual([1,2,3,4,5,6].map(getOnboardingPathForStep),['/onboarding/region','/onboarding/industry','/onboarding/business','/onboarding/objectives','/onboarding/plan','/onboarding/connect-data']);
 assert.match(read('app/router/routePaths.js'),/onboardingPlanCustom: '\/onboarding\/plan\/custom'/);
});
test('progress is real tenant-scoped HTTP data, with no preview persistence',()=>{
 const api=read('features/onboarding/api/onboardingApi.js'),store=read('features/onboarding/store/onboardingStore.js');
 assert.match(api,/httpClient.get\('\/onboarding\/state'\)/);assert.match(api,/httpClient.put/);
 assert.match(store,/expected_revision/);assert.doesNotMatch(store,/localStorage\.setItem|ceopro_onboarding_preview|DEFAULT_CUSTOM_PLAN/);
});
test('cached incomplete progress cannot redirect ahead of an authoritative refetch',()=>{
 const guard=read('features/onboarding/components/OnboardingGate.jsx');
 assert.match(guard,/query.isPending \|\| query.isFetching/);assert.match(guard,/step>query.data.currentStep/);
 const plans=read('features/billing/pages/OnboardingPlanSelectionPage.jsx');
 assert.match(plans,/OriginalPlanSelector/);assert.match(plans,/saveOnboardingPlan/);assert.doesNotMatch(plans,/useEffect/); // Active trials render a deliberate choice; they never trigger automatic navigation.
});
test('original onboarding labels exist in both locales and review uses server trial evidence',()=>{
 for(const locale of ['en','ar']){
  const labels=JSON.parse(read('assets/locales/'+locale+'.json'));
  assert.ok(labels.onboarding.region.title);assert.ok(labels.onboarding.objectives.title);assert.ok(labels.dataConnections.skip);
 }
 const review=read('features/billing/pages/OnboardingPaymentPage.jsx');assert.match(review,/PlanSummaryCard/);assert.match(review,/checkoutTrialEndsAt/);assert.match(review,/CouponInput/);
});

test('Custom builder renders the real Python modules contract, separately from numeric allowances',()=>{
 const builder=read('features/billing/pages/CustomPlanBuilderPage.jsx');
 assert.match(builder,/catalog.modules/);assert.doesNotMatch(builder,/catalog.includedFeatures/);
 assert.match(builder,/enabled_features/);assert.match(builder,/monitoringFrequencyMinutes/);
});

test('original result pages require exact server Checkout correlation before continuing setup',()=>{
 const hook=read('features/billing/hooks/useSubscriptionConfirmation.js');assert.match(hook,/billing\/checkout-status/);assert.match(hook,/session_id:id/);
 const notice=read('features/billing/components/CheckoutReturnNotice.jsx');assert.match(notice,/query.data\?\.state==='confirmed'/);assert.match(notice,/setup.data.highestCompletedStep>=5/);
 const success=read('features/onboarding/pages/OnboardingSubscriptionSuccessPage.jsx');assert.match(success,/SubscriptionResult/);assert.doesNotMatch(success,/completePlanStep/);
});
