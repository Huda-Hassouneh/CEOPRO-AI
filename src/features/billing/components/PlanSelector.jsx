import { Zap } from 'lucide-react';
import SegmentedControl from '../../../shared/components/ui/SegmentedControl.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { BILLING_PERIODS, PREVIEW_PLANS, getPreviewPlan } from '../config/billingPreviewData.js';
import { PlanCard } from './PlanCard.jsx';

export function PlanSelector({ selectedPlan, billingPeriod, onPlanSelect, onPeriodChange, onBuildCustom }) {
  const { t } = useI18n();
  const trialPlan = getPreviewPlan('pro');
  const periods = BILLING_PERIODS.map((period) => ({
    value: period.value,
    label: period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months }),
    badge: Object.values(PREVIEW_PLANS).every(p => p.discounts[period.value] === period.discountPercent) && period.discountPercent ? t('billing.periods.savePercent', { percent: period.discountPercent }) : undefined,
  }));

  return (
    <div>
      {trialPlan.status === 'active' && trialPlan.trialDays > 0 && <div className="ceopro-trial-banner">
        <Zap size={20} fill="currentColor" aria-hidden="true" />
        <span><strong>{t('billing.trial.title', { days: trialPlan.trialDays })}</strong><small>{t('billing.trial.description')}</small></span>
        <b>{t('billing.trial.badge', { days: trialPlan.trialDays })}</b>
      </div>}
      <div className="ceopro-billing-period-row">
        <SegmentedControl name="billing-period" value={billingPeriod} options={periods} onChange={onPeriodChange} ariaLabel={t('billing.periods.label')} />
      </div>
      <div className="ceopro-plan-grid">
        {Object.values(PREVIEW_PLANS).map((plan) => (
          <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} selected={selectedPlan === plan.id} onSelect={onPlanSelect} onBuild={onBuildCustom} />
        ))}
      </div>
    </div>
  );
}
