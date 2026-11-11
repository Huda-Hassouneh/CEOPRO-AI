import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { PlanSelector } from '../../billing/components/PlanSelector.jsx';
import { SectionHeading, useLanding } from '../components/LandingPrimitives.jsx';
import '../../billing/styles/Billing.css';
import { PolicyLinks } from '../../legal/PolicyLinks.jsx';

const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || '';

export function PricingSection() {
  const { t } = useLanding();
  const navigate = useNavigate();
  const [period, setPeriod] = useState('monthly');
  // Registration and provider-backed trial eligibility remain separate guards.
  const choose = (plan) => {
    if (!plan.selfServe) {
      if (SUPPORT_EMAIL) window.location.href = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('KEEL Custom plan')}`;
      else navigate(routePaths.contact);
      return;
    }
    navigate(routePaths.welcome);
  };
  return <section className="lp-section lp-tinted" id="pricing"><div className="lp-container"><SectionHeading section="pricing" centered /><PlanSelector billingPeriod={period} onPeriodChange={setPeriod} onPlanSelect={choose} /><p className="lp-fineprint lp-centered">{t('pricing.note')}</p><PolicyLinks /></div></section>;
}
