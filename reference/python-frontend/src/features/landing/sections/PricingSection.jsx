import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { PlanSelector } from '../../billing/components/PlanSelector.jsx';
import { SectionHeading, useLanding } from '../components/LandingPrimitives.jsx';
import '../../billing/styles/Billing.css';

const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || '';

export function PricingSection() {
  const { t } = useLanding();
  const navigate = useNavigate();
  const [period, setPeriod] = useState('monthly');
  // Every new company starts on the free trial; the plan is chosen in
  // Billing once they've seen the product with their own data.
  const choose = (plan) => {
    if (!plan.selfServe) {
      if (SUPPORT_EMAIL) window.location.href = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('KEEL Custom plan')}`;
      return;
    }
    navigate(routePaths.welcome);
  };
  return <section className="lp-section lp-tinted" id="pricing"><div className="lp-container"><SectionHeading section="pricing" centered /><PlanSelector billingPeriod={period} onPeriodChange={setPeriod} onPlanSelect={choose} /><p className="lp-fineprint lp-centered">{t('pricing.note')}</p></div></section>;
}
