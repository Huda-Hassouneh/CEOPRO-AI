import { CalendarDays, CreditCard, Crown } from 'lucide-react';
import Badge from '../../../shared/components/ui/Badge.jsx';
import { formatMoney } from '../utils/money.js';

export function CurrentPlanCard({ subscription, plan, locale, t, formatDate, actions }) {
  const price = plan?.prices?.[subscription.billingPeriod];
  const trialEnd = subscription.status === 'trial' && subscription.trialEndsAt ? new Date(subscription.trialEndsAt) : null;
  const daysRemaining = trialEnd ? Math.max(0, Math.ceil((trialEnd.getTime() - Date.now()) / 86400000)) : null;
  const statusVariant = subscription.status === 'active' ? 'light-success' : subscription.status === 'trial' ? 'primary' : 'error';
  const name = plan?.name?.[locale] || plan?.name?.en || subscription.planName;
  const months = price?.months || 1;
  return <section className="billing-current-plan" aria-labelledby="current-plan-title">
    <div className="billing-current-plan__identity">
      <span className="billing-current-plan__icon"><Crown size={24} /></span>
      <div>
        <small id="current-plan-title">{t('billing.management.currentPlanTitle')}</small>
        <h2>{subscription.status === 'trial' ? t('billing.management.planTrial', { plan: name }) : name}</h2>
        <Badge variant={statusVariant}>{t(`billing.management.status.${subscription.status}`)}</Badge>
      </div>
    </div>
    <dl>
      {subscription.hasSubscription && <div><dt><CreditCard size={14} />{t('billing.management.billingCycle')}</dt><dd>{months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months })}</dd></div>}
      {subscription.hasSubscription && price && <div><dt>{t('billing.management.planPrice')}</dt><dd>{formatMoney(price.amount, price.currency, locale)}</dd></div>}
      {subscription.renewsAt && <div><dt><CalendarDays size={14} />{t('billing.management.nextBillingDate')}</dt><dd>{formatDate(subscription.renewsAt)}</dd></div>}
      {subscription.endsAt && <div><dt><CalendarDays size={14} />{t('billing.management.accessEnds')}</dt><dd>{formatDate(subscription.endsAt)}</dd></div>}
      {trialEnd && <div><dt><CalendarDays size={14} />{t('billing.management.trialEndDate')}</dt><dd>{formatDate(trialEnd)}{daysRemaining != null && <small>{t('billing.management.daysRemaining', { count: daysRemaining })}</small>}</dd></div>}
    </dl>
    {actions && <div className="billing-current-plan__actions">{actions}</div>}
  </section>;
}
