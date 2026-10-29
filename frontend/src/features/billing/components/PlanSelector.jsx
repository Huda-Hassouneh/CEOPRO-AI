import { Zap } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { usePlans } from '../hooks/usePlans.js';
import { PlanCard, PlanSharedFeatures } from './PlanCard.jsx';
import { PeriodSelector } from './PeriodSelector.jsx';

// The public plan catalog (landing page): real prices from the backend.
export function PlanSelector({ billingPeriod, onPeriodChange, onPlanSelect }) {
  const { t, locale } = useI18n();
  const plansQuery = usePlans();
  if (plansQuery.isPending) return <div className="ceopro-plan-grid">{[0, 1, 2].map((i) => <Skeleton key={i} height="320px" variant="rectangular" />)}</div>;
  if (plansQuery.isError) return null;
  const plans = plansQuery.data.plans;
  const trialPlan = plans.find((plan) => plan.trialDays > 0);
  return (
    <div>
      {trialPlan && <div className="ceopro-trial-banner">
        <Zap size={20} fill="currentColor" aria-hidden="true" />
        <span><strong>{t('billing.trial.title', { days: trialPlan.trialDays })}</strong><small>{t('billing.trial.description')}</small></span>
        <b>{t('billing.trial.badge', { days: trialPlan.trialDays })}</b>
      </div>}
      <div className="ceopro-billing-period-row"><PeriodSelector plans={plans} value={billingPeriod} onChange={onPeriodChange} /></div>
      <div className="ceopro-plan-grid" style={{ '--plan-count': plans.length }}>
        {plans.map((plan) => <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} onAction={onPlanSelect}
          actionLabel={plan.selfServe ? t('billing.plans.startWith', { plan: plan.name?.[locale] || plan.name?.en }) : t('billing.management.contactSales')} />)}
      </div>
      <PlanSharedFeatures plans={plans} />
    </div>
  );
}
