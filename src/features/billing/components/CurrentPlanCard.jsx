import { CalendarDays, CreditCard, Crown } from 'lucide-react';
import Badge from '../../../shared/components/ui/Badge.jsx';
import { formatPreviewUsd, getBillingPeriod, getPreviewPlanPrice } from '../config/billingPreviewData.js';

export function CurrentPlanCard({ subscription, plan, locale, t, formatDate }) {
  const period = getBillingPeriod(subscription.billingPeriod);
  const pricing = getPreviewPlanPrice(plan.id, subscription.billingPeriod);
  const trialEnd = subscription.status === 'trial' && subscription.trialEndsAt ? new Date(subscription.trialEndsAt) : null;
  const daysRemaining = trialEnd ? Math.max(0, Math.ceil((trialEnd.getTime() - Date.now()) / 86400000)) : null;
  const statusVariant = subscription.status === 'active' ? 'light-success' : subscription.status === 'trial' ? 'primary' : 'error';

  return <section className="billing-current-plan" aria-labelledby="current-plan-title">
    <div className="billing-current-plan__identity">
      <span className="billing-current-plan__icon"><Crown size={24} /></span>
      <div><small id="current-plan-title">{t('billing.management.currentPlanTitle')}</small><h2>{subscription.status === 'trial' ? t('billing.management.planTrial', { plan: (plan.name?.[locale] || t(plan.nameKey)) }) : (plan.name?.[locale] || t(plan.nameKey))}</h2><Badge variant={statusVariant}>{t(`billing.management.status.${subscription.status}`)}</Badge></div>
    </div>
    <dl>
      <div><dt><CreditCard size={14} />{t('billing.management.billingCycle')}</dt><dd>{period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months })}</dd></div>
      {pricing && <div><dt>{t('billing.management.planPrice')}</dt><dd>{formatPreviewUsd(pricing.total, locale)}</dd></div>}
      {subscription.renewsAt && <div><dt><CalendarDays size={14} />{t('billing.management.nextBillingDate')}</dt><dd>{formatDate(subscription.renewsAt)}</dd></div>}
      {trialEnd && <div><dt><CalendarDays size={14} />{t('billing.management.trialEndDate')}</dt><dd>{formatDate(trialEnd)}{daysRemaining != null && <small>{t('billing.management.daysRemaining', { count: daysRemaining })}</small>}</dd></div>}
    </dl>
    {subscription.preview && <span className="billing-preview-label">{t('billing.management.previewData')}</span>}
  </section>;
}

