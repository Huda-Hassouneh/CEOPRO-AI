import { Check, X } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { PREVIEW_CUSTOM_QUOTE, formatPreviewUsd, getBillingPeriod, getPreviewPlan, getPreviewPlanPrice } from '../config/billingPreviewData.js';

export function SubscriptionResult({ status, planId = 'pro', checkoutMode = 'paid', billingPeriod = 'monthly', onPrimary, onBack }) {
  const { locale, t } = useI18n();
  const success = status === 'success';
  const plan = getPreviewPlan(planId);
  const trial = plan.trialDays > 0 && checkoutMode === 'trial';
  const pricing = getPreviewPlanPrice(plan.id, billingPeriod);
  const amount = trial ? 0 : plan.id === 'custom' ? PREVIEW_CUSTOM_QUOTE.amount : pricing?.total ?? 0;

  return (
    <section className={`ceopro-subscription-result ${success ? 'is-success' : 'is-failed'}`}>
      <span className="ceopro-subscription-result__icon" aria-hidden="true">{success ? <Check size={40} /> : <X size={40} />}</span>
      <h1>{t(`billing.result.${status}.title`)}</h1>
      <p>{t(`billing.result.${status}.description`)}</p>
      <div className="ceopro-subscription-result__card">
        <strong>{(plan.name?.[locale] || t(plan.nameKey))}</strong><span>{(plan.description?.[locale] || t(plan.descriptionKey))}</span>
        <dl>
          <div><dt>{t('billing.payment.billingCycle')}</dt><dd>{getBillingPeriod(billingPeriod).months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: getBillingPeriod(billingPeriod).months })}</dd></div>
          <div><dt>{t('billing.result.amount')}</dt><dd>{formatPreviewUsd(amount, locale)}</dd></div>
          {!success && <div><dt>{t('billing.result.paymentMethod')}</dt><dd>{t('billing.result.previewMethod')}</dd></div>}
        </dl>
      </div>
      <p className="ceopro-subscription-result__preview">{t('billing.payment.previewNotice')}</p>
      <div className="ceopro-subscription-result__actions">
        {!success && <Button variant="outline" onClick={onBack}>{t('onboarding.common.back')}</Button>}
        <Button onClick={onPrimary}>{t(`billing.result.${status}.action`)}</Button>
      </div>
    </section>
  );
}

