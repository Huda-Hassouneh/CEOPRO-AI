import { Landmark } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import '../styles/CustomPlan.css';

export function CustomPlanCard({ returnTo = routePaths.billing }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const target = (returnTo === routePaths.onboardingPlan ? routePaths.onboardingPlanCustom : routePaths.customPlanBuilder) + '?returnTo=' + encodeURIComponent(returnTo);
  return <article className="ceopro-plan-card custom-plan-card">
    <header><span className="ceopro-plan-card__icon"><Landmark size={21} aria-hidden="true" /></span><div><h2>{t('billing.customPlan.cardTitle')}</h2><p>{t('billing.customPlan.cardDescription')}</p></div></header>
    <div className="ceopro-plan-card__price"><strong>{t('billing.plans.customPricing')}</strong></div>
    <p className="custom-plan-card__summary">{t('billing.customPlan.cardSummary')}</p>
    <Button variant="outline" fullWidth onClick={() => navigate(target)}>{t('billing.customPlan.buildAction')}</Button>
  </article>;
}