import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { PlanSelector } from '../../billing/components/PlanSelector.jsx';
import { BILLING_PERIODS, getPreviewPlan } from '../../billing/config/billingPreviewData.js';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';
import { SectionHeading, useLanding } from '../components/LandingPrimitives.jsx';
import '../../billing/styles/Billing.css';

export function PricingSection() {
  const { t } = useLanding();
  const navigate = useNavigate();
  // Public price exploration does not mutate onboarding. Save only an explicit CTA choice.
  const [period, setPeriod] = useState(BILLING_PERIODS[0].value);
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const setBillingPeriod = useOnboardingStore((state) => state.setBillingPeriod);
  const choose = (plan) => {
    setPlanChoice(plan, getPreviewPlan(plan).trialDays > 0 ? 'trial' : 'paid');
    setBillingPeriod(period);
    navigate(plan === 'custom' ? routePaths.onboardingPlanCustom : routePaths.signup);
  };
  return <section className="lp-section lp-tinted" id="pricing"><div className="lp-container"><SectionHeading section="pricing" centered /><PlanSelector billingPeriod={period} onPeriodChange={setPeriod} onPlanSelect={choose} onBuildCustom={() => choose('custom')} /><p className="lp-fineprint lp-centered">{t('pricing.note')}</p></div></section>;
}
