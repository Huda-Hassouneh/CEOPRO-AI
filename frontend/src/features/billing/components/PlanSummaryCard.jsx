import { Check, Crown, Sprout } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { describeBillingOption } from '../utils/billingPeriodPresentation.js';
import { ExistingTrialNotice } from './ExistingTrialNotice.jsx';

const planIcons = {
  starter: Sprout,
  growth: Crown,
  enterprise: Crown,
};

export function PlanSummaryCard({ plan = {}, billingPeriod, checkoutMode = 'paid', checkoutTrialEndsAt = null, promotionEntered = false, selected = false, trialAvailable = false, changePlanAction, children }) {
  const { locale, t } = useI18n();
  const planNameSafe = String(plan.name || '').trim().toLowerCase();
  // Catalog duration and an already-issued trial's cutoff are different facts.
  // Never replace configured days with a rounded countdown or restart a trial.
  const trialDays = Number(plan.trialDays ?? plan.trialPeriodDays ?? plan.trialPeriodValue ?? 0);
  const trialEnd = checkoutTrialEndsAt ? new Date(checkoutTrialEndsAt * 1000) : null;
  const isTrial = checkoutMode === 'trial' && trialEnd && !Number.isNaN(trialEnd.getTime());
  const selectedPricingOption =
    plan.pricingOptions?.find((option) => option.period === billingPeriod) ||
    plan.pricingOptions?.[0];
  const discountPercent = selectedPricingOption?.discountPercent || 0;
  const totalPrice = selectedPricingOption?.totalPrice ?? plan.basePrice ?? 0;
  const subtotal = discountPercent > 0
    ? totalPrice / (1 - discountPercent / 100)
    : totalPrice;
  const discountAmount = subtotal - totalPrice;
  const dueToday = isTrial || trialAvailable ? 0 : totalPrice;
  const PlanIcon = planIcons[planNameSafe] || Sprout;
  const finalPlanName = plan.displayName || (locale === 'ar' && plan.name_ar ? plan.name_ar : plan.name) || '';
  const finalDescription = plan.displayDescription || plan.description || '';

  const formatCurrency = (amount) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO-u-nu-latn' : 'en-US', {
      style: 'currency',
      currency: plan.currency || 'USD',
    }).format(amount || 0);
  const formatNumber = (number) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO-u-nu-latn' : 'en-US').format(number);

  return (
    <aside className={`ceopro-plan-summary${selected ? ' ceopro-plan-summary--selected' : ''}`} aria-label={selected ? t('billing.payment.selectedPlan') : undefined}>
      <header>
        <div className="ceopro-plan-summary__identity">
          <span className="ceopro-plan-summary__icon">{selected ? <Check size={20} aria-hidden="true" /> : <PlanIcon size={17} />}</span>
          <div>
            {selected && <span className="ceopro-plan-summary__selected-label">{t('billing.payment.selectedPlan')}</span>}
            <h2>{selected ? finalPlanName : t('billing.payment.yourPlan')}</h2>
            <small>{finalDescription}</small>
          </div>
        </div>
        {selected ? changePlanAction : <span>{finalPlanName}</span>}
      </header>

      {isTrial && <ExistingTrialNotice endsAt={checkoutTrialEndsAt} />}
      {selected && <div className="ceopro-plan-summary__offer">
        <p className="ceopro-plan-summary__headline-price">
          <strong>{formatCurrency(totalPrice)}</strong>
          <span>{describeBillingOption(selectedPricingOption || {}, t)}</span>
        </p>
        {trialAvailable && <span className="ceopro-plan-summary__trial-badge">{t('billing.payment.trial', { days: trialDays })}</span>}
        {(trialAvailable || isTrial) && <p className="ceopro-plan-summary__renewal">{t('billing.payment.postTrialBilling', {
          amount: formatCurrency(totalPrice), period: describeBillingOption(selectedPricingOption || {}, t),
        })}</p>}
        {promotionEntered && <p className="ceopro-plan-summary__renewal">{t('billing.payment.stripeConfirmsPromotion')}</p>}
        <div className="ceopro-plan-summary__total">
          <span>{t(promotionEntered ? 'billing.payment.catalogBeforePromotion' : 'billing.payment.totalDueToday')}</span>
          <strong className={trialAvailable || isTrial ? 'is-success' : ''}>{formatCurrency(dueToday)}</strong>
        </div>
      </div>}

      {children}
      {selected && <details className="ceopro-plan-summary__details">
        <summary>{t('billing.payment.planDetails')}</summary>
        <PlanFeatures plan={plan} locale={locale} t={t} formatNumber={formatNumber} />
      </details>}
      {!selected && <PlanFeatures plan={plan} locale={locale} t={t} formatNumber={formatNumber} />}

      {!selected && <div className="ceopro-plan-summary__price">
        <div>
          <span>{t('billing.payment.billingCycle')}</span>
          <strong>{describeBillingOption(selectedPricingOption || {}, t)}</strong>
        </div>
        {!isTrial && <div>
          <span>{t('billing.payment.configuredTrial')}</span>
          <strong>{trialDays > 0 ? t('billing.payment.trial', { days: trialDays }) : t('billing.payment.noTrial')}</strong>
        </div>}
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
              <span>{t('billing.payment.afterExistingTrialEnd')}</span>
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
      </div>}

      {!selected && <>
        {promotionEntered&&<p role="note">{t('billing.payment.stripeConfirmsPromotion')}</p>}
        <div className="ceopro-plan-summary__total">
          <span>{t(promotionEntered?'billing.payment.catalogBeforePromotion':'billing.payment.totalDueToday')}</span>
          <strong className={isTrial ? 'is-success' : ''}>{formatCurrency(dueToday)}</strong>
        </div>
      </>}
    </aside>
  );
}

function PlanFeatures({ plan, locale, t, formatNumber }) {
  return <ul>
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
      </ul>;
}
