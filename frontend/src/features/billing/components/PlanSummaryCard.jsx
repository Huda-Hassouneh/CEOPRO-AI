import { Check, Crown, Sprout } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { describeBillingOption } from '../utils/billingPeriodPresentation.js';

const planIcons = {
  starter: Sprout,
  growth: Crown,
  enterprise: Crown,
};

export function PlanSummaryCard({ plan = {}, billingPeriod, checkoutMode = 'paid', checkoutTrialEndsAt = null, promotionEntered = false }) {
  const { locale, t } = useI18n();
  const planNameSafe = String(plan.name || '').trim().toLowerCase();
  // Catalog duration and an already-issued trial's cutoff are different facts.
  // Never replace configured days with a rounded countdown or restart a trial.
  const trialDays = Number(plan.trialDays ?? plan.trialPeriodDays ?? plan.trialPeriodValue ?? 0);
  const trialEnd = checkoutTrialEndsAt ? new Date(checkoutTrialEndsAt * 1000) : null;
  const isTrial = checkoutMode === 'trial' && trialEnd && !Number.isNaN(trialEnd.getTime());
  const trialEndLabel = isTrial ? new Intl.DateTimeFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC',
  }).format(trialEnd) : null;
  const selectedPricingOption =
    plan.pricingOptions?.find((option) => option.period === billingPeriod) ||
    plan.pricingOptions?.[0];
  const discountPercent = selectedPricingOption?.discountPercent || 0;
  const totalPrice = selectedPricingOption?.totalPrice ?? plan.basePrice ?? 0;
  const subtotal = discountPercent > 0
    ? totalPrice / (1 - discountPercent / 100)
    : totalPrice;
  const discountAmount = subtotal - totalPrice;
  const dueToday = isTrial ? 0 : totalPrice;
  const PlanIcon = planIcons[planNameSafe] || Sprout;
  const finalPlanName = plan.displayName || plan.name || '';
  const finalDescription = plan.displayDescription || plan.description || '';

  const formatCurrency = (amount) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO-u-nu-latn' : 'en-US', {
      style: 'currency',
      currency: plan.currency || 'USD',
    }).format(amount || 0);
  const formatNumber = (number) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO-u-nu-latn' : 'en-US').format(number);

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
        <span>
          {isTrial
            ? t('billing.payment.planTrial', { plan: finalPlanName })
            : finalPlanName}
        </span>
      </header>

      <ul>
        {Object.entries(plan.features || {}).map(([featureCode, feature]) => {
          const featureName =
            locale === 'ar' && feature?.name_ar
              ? feature.name_ar
              : feature?.name || featureCode;
          const isBoolean = feature?.type === 'boolean';
          const limitText = isBoolean
            ? t('billing.management.included')
            : feature?.limitValue === null
              ? t('common.unlimited')
              : formatNumber(feature?.limitValue ?? 0);
          const unitText =
            locale === 'ar' ? feature?.unit_ar || feature?.unit : feature?.unit;

          return (
            <li className="ceopro-plan-summary__feature" key={featureCode}>
              <Check size={14} />
              <span>{featureName}</span>
              <strong>
                {limitText}
                {!isBoolean && feature?.limitValue !== null && unitText ? ` ${unitText}` : ''}
              </strong>
            </li>
          );
        })}
      </ul>

      <div className="ceopro-plan-summary__price">
        <div>
          <span>{t('billing.payment.billingCycle')}</span>
          <strong>{describeBillingOption(selectedPricingOption || {}, t)}</strong>
        </div>
        <div>
          <span>{t('billing.payment.configuredTrial')}</span>
          <strong>{trialDays > 0 ? t('billing.payment.trial', { days: trialDays }) : t('billing.payment.noTrial')}</strong>
        </div>
        {discountPercent > 0 && (
          <>
            <div>
              <span>{t('billing.payment.subtotal')}</span>
              <strong>{formatCurrency(subtotal)}</strong>
            </div>
            <div>
              <span>{t('billing.payment.discount', { percent: discountPercent })}</span>
              <strong>-{formatCurrency(discountAmount)}</strong>
            </div>
          </>
        )}
        {isTrial ? (
          <>
            <div>
              <span>{t('billing.payment.afterExistingTrial', { date: trialEndLabel })}</span>
              <strong>{formatCurrency(totalPrice)}</strong>
            </div>
            <div>
              <span className="is-success">
                {t('billing.payment.existingTrial')}
              </span>
              <strong className="is-success">{formatCurrency(0)}</strong>
            </div>
          </>
        ) : (
          <div>
            <span>{t('billing.payment.previewTotal')}</span>
            <strong>{formatCurrency(totalPrice)}</strong>
          </div>
        )}
      </div>

      {isTrial && <p role="note">{t('billing.payment.preservedTrial', { date: trialEndLabel })}</p>}
      {promotionEntered&&<p role="note">{t('billing.payment.stripeConfirmsPromotion')}</p>}
      <div className="ceopro-plan-summary__total">
        <span>{t(promotionEntered?'billing.payment.catalogBeforePromotion':'billing.payment.totalDueToday')}</span>
        <strong className={isTrial ? 'is-success' : ''}>{formatCurrency(dueToday)}</strong>
      </div>
    </aside>
  );
}
