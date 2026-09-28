import { Check, Crown, SlidersHorizontal, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { describeBillingOption, getBillingOptionCount, getBillingOptionUnit } from '../utils/billingPeriodPresentation.js';

const planIcons = {
  starter: Sprout,
  standard: Sprout,
  growth: Crown,
  pro: Crown,
  enterprise: Crown,
};

export function PlanCard({
  plan = {},
  selected,
  currentPlan = false,
  billingPeriod,
  onSelect,
  actionLabel,
  actionDisabled = false,
}) {
  const { locale, t } = useI18n();
  const planNameSafe = plan.name?.toLowerCase() || '';
  const Icon = plan.isCustomBuilder ? SlidersHorizontal : (planIcons[planNameSafe] || Sprout);
  const hasTrial = Number(plan.trialPeriodValue) > 0;
  const selectedPricingOption =
    plan.pricingOptions?.find((option) => option.period === billingPeriod) ||
    plan.pricingOptions?.[0];
  const supportsPeriod = plan.isCustomBuilder || plan.pricingOptions?.some((option) => option.period === billingPeriod);
  const intervalUnit = getBillingOptionUnit(selectedPricingOption || {});
  const intervalCount = getBillingOptionCount(selectedPricingOption || {});
  const isMultiMonth = intervalUnit !== 'day' && (selectedPricingOption?.months ?? intervalCount) > 1;
  const finalTotal = selectedPricingOption?.totalPrice ?? plan.basePrice ?? 0;
  const monthlyEquivalent = selectedPricingOption?.monthlyEquivalent ?? plan.basePrice ?? 0;

  const formatCurrency = (amount) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
      style: 'currency',
      currency: plan.currency || 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount || 0);

  const finalPlanName = plan.displayName || plan.name || '';
  const finalDescription = plan.displayDescription || plan.description || '';

  return (
    <article
      className={`ceopro-plan-card ${selected || currentPlan ? 'is-selected' : ''} ${
        plan.featured ? 'is-featured' : ''
      } ${currentPlan ? 'is-current' : ''}`.trim()}
    >
      {plan.featured && (
        <span className="ceopro-plan-card__featured">{t('billing.plans.mostPopular')}</span>
      )}

      <header>
        <span className="ceopro-plan-card__icon"><Icon size={21} /></span>
        <div>
          <h2>
            {finalPlanName}
            {currentPlan && (
              <span className="ceopro-plan-card__current">{t('billing.management.currentPlan')}</span>
            )}
          </h2>
          <p>{finalDescription}</p>
        </div>
      </header>

      <div className="ceopro-plan-card__price">
        {plan.isCustomBuilder ? (
          <>
            <strong>{t('billing.plans.customPricing')}</strong>
            <small>{t('billing.custom.previewPriceNote') || 'Your price is calculated securely from the features and quotas you choose.'}</small>
          </>
        ) : (
          <>
            <strong>{formatCurrency(finalTotal)}</strong>
            <span>
              / {intervalUnit === 'day'
                ? describeBillingOption(selectedPricingOption, t)
                : intervalUnit === 'year'
                  ? describeBillingOption(selectedPricingOption, t)
                  : isMultiMonth
                    ? t('billing.periods.monthCount', { months: intervalCount })
                    : t('billing.periods.month')}
            </span>
            {isMultiMonth && (
              <small>{t('billing.periods.monthlyEquivalent', { price: formatCurrency(monthlyEquivalent) })}</small>
            )}
          </>
        )}
      </div>

      <ul>
        {Object.entries(plan.features || {}).map(([featureCode, feature]) => {
          const limitText = feature.limitValue === null
            ? t('common.unlimited')
            : new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US').format(feature.limitValue);
          const displayUnit = locale === 'ar' ? feature.unit_ar || feature.unit : feature.unit;
          const featureName = locale === 'ar' && feature.name_ar ? feature.name_ar : feature.name;
          return (
            <li key={featureCode}>
              <Check size={15} aria-hidden="true" />
              <span>{limitText}{displayUnit && feature.limitValue !== null ? ` ${displayUnit}` : ''} {featureName}</span>
            </li>
          );
        })}
      </ul>

      <Button
        variant={plan.featured && !actionDisabled ? 'primary' : 'outline'}
        fullWidth
        onClick={() => onSelect?.(plan.id)}
        disabled={actionDisabled || plan.isActive === false || !supportsPeriod}
      >
        {actionLabel || (hasTrial
          ? t('billing.plans.pro.action', { days: plan.trialPeriodValue })
          : t('billing.payment.complete'))}
      </Button>
    </article>
  );
}
