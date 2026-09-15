import { Check, Crown, Landmark, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { formatPreviewUsd, getPlanFeatureRows, getPreviewPlanPrice } from '../config/billingPreviewData.js';

const planIcons = { standard: Sprout, pro: Crown, custom: Landmark };

export function PlanCard({ plan, selected, currentPlan = false, billingPeriod, onSelect, onBuild, actionLabel, actionDisabled = false }) {
  const { locale, t } = useI18n();
  const Icon = planIcons[plan.id];
  const action = plan.id === 'custom' ? onBuild : () => onSelect(plan.id);
  const pricing = getPreviewPlanPrice(plan.id, billingPeriod);

  return (
    <article className={`ceopro-plan-card ${selected || currentPlan ? 'is-selected' : ''} ${plan.featured ? 'is-featured' : ''} ${currentPlan ? 'is-current' : ''}`.trim()}>
      {plan.featured && <span className="ceopro-plan-card__featured">{t('billing.plans.mostPopular')}</span>}
      <header>
        <span className="ceopro-plan-card__icon"><Icon size={21} /></span>
        <div><h2>{plan.name?.[locale] || t(plan.nameKey)}{currentPlan && <span className="ceopro-plan-card__current">{t('billing.management.currentPlan')}</span>}</h2><p>{plan.description?.[locale] || t(plan.descriptionKey)}</p></div>
      </header>
      <div className="ceopro-plan-card__price">
        {!pricing
          ? <strong>{t('billing.plans.customPricing')}</strong>
          : <>
            <strong>{formatPreviewUsd(pricing.total, locale)}</strong>
            <span>/ {pricing.isMultiMonth ? t('billing.periods.monthCount', { months: pricing.months }) : t('billing.periods.month')}</span>
            {pricing.isMultiMonth && <small>{t('billing.periods.monthlyEquivalent', { price: formatPreviewUsd(pricing.monthlyEquivalent, locale) })}</small>}
          </>}
      </div>
      <ul>
        {getPlanFeatureRows(plan).map(({ key, value }) => (
          <li key={key}><Check size={15} aria-hidden="true" /><span>{t(`billing.features.${key}`, { value })}</span></li>
        ))}
      </ul>
      <Button variant={plan.featured && !actionDisabled ? 'primary' : 'outline'} fullWidth onClick={action} disabled={actionDisabled || plan.status === 'inactive' || !plan.billingOptions?.includes(billingPeriod)}>
        {actionLabel || (plan.id === 'pro' && !plan.trialDays ? t('billing.management.reviewSubscription') : t(plan.actionKey, { days: plan.trialDays }))}
      </Button>
    </article>
  );
}
