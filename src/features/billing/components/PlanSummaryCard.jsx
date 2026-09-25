import { Check, Crown, Sprout } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

const planIcons = {
  starter: Sprout,
  standard: Sprout,
  growth: Crown,
  pro: Crown,
  enterprise: Crown,
};

export function PlanSummaryCard({ plan = {}, billingPeriod, checkoutMode = 'paid' }) {
  const { locale, t } = useI18n();
  const planNameSafe = plan.name?.toLowerCase() || '';
  const isTrial = Number(plan.trialPeriodValue) > 0 && checkoutMode === 'trial';
  const selectedPricingOption =
    plan.pricingOptions?.find((option) => option.period === billingPeriod) || plan.pricingOptions?.[0];
  const months = selectedPricingOption?.months || 1;
  const discountPercent = selectedPricingOption?.discountPercent || 0;
  const totalPrice = selectedPricingOption?.totalPrice ?? plan.basePrice ?? 0;
  const subtotal = discountPercent > 0 ? totalPrice / (1 - discountPercent / 100) : totalPrice;
  const discountAmount = subtotal - totalPrice;
  const dueToday = isTrial ? 0 : totalPrice;
  const PlanIcon = planIcons[planNameSafe] || Sprout;
  const finalPlanName = plan.displayName || plan.name || '';
  const finalDescription = plan.displayDescription || plan.description || '';

  const formatCurrency = (amount) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
      style: 'currency',
      currency: plan.currency || 'USD',
    }).format(amount || 0);
  const formatNumber = (number) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US').format(number);

  return (
    <aside className="ceopro-plan-summary">
      <header>
        <div className="ceopro-plan-summary__identity">
          <span className="ceopro-plan-summary__icon"><PlanIcon size={17} /></span>
          <div>
            <h2>{t('billing.payment.yourPlan')}</h2>
            <small>{finalDescription}</small>
          </div>
        </div>
        <span>{isTrial ? t('billing.payment.proTrial') : finalPlanName}</span>
      </header>

      <ul>
        {Object.entries(plan.features || {}).map(([featureCode, feature]) => {
          const featureName = locale === 'ar' && feature.name_ar ? feature.name_ar : feature.name;
          const limitText = feature.limitValue === null ? t('common.unlimited') : formatNumber(feature.limitValue);
          const unitText = locale === 'ar' ? feature.unit_ar || feature.unit : feature.unit;
          return (
            <li className="ceopro-plan-summary__feature" key={featureCode}>
              <Check size={14} />
              <span>{featureName}</span>
              <strong>{limitText} {feature.limitValue !== null ? unitText : ''}</strong>
            </li>
          );
        })}
      </ul>

      <div className="ceopro-plan-summary__price">
        <div>
          <span>{t('billing.payment.billingCycle')}</span>
          <strong>{months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months })}</strong>
        </div>
        {discountPercent > 0 && (
          <>
            <div><span>{t('billing.payment.subtotal')}</span><strong>{formatCurrency(subtotal)}</strong></div>
            <div><span>{t('billing.payment.discount', { percent: discountPercent })}</span><strong>-{formatCurrency(discountAmount)}</strong></div>
          </>
        )}
        {isTrial ? (
          <>
            <div><span>{t('billing.payment.afterTrial', { days: plan.trialPeriodValue })}</span><strong>{formatCurrency(totalPrice)}</strong></div>
            <div><span className="is-success">{t('billing.payment.trial', { days: plan.trialPeriodValue })}</span><strong className="is-success">{formatCurrency(0)}</strong></div>
          </>
        ) : (
          <div><span>{t('billing.payment.previewTotal')}</span><strong>{formatCurrency(totalPrice)}</strong></div>
        )}
      </div>

      <div className="ceopro-plan-summary__total">
        <span>{t('billing.payment.totalDueToday')}</span>
        <strong className={isTrial ? 'is-success' : ''}>{formatCurrency(dueToday)}</strong>
      </div>
    </aside>
  );
}
