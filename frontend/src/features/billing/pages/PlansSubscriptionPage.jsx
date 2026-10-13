import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { CurrentPlanCard } from '../components/CurrentPlanCard.jsx';
import { UsageLimitGrid } from '../components/UsageLimitGrid.jsx';
import { UpgradeRecommendation } from '../components/UpgradeRecommendation.jsx';
import { PlanCard } from '../components/PlanCard.jsx';
import { PlanComparisonTable } from '../components/PlanComparisonTable.jsx';
import { PeriodSelector } from '../components/PeriodSelector.jsx';
import { InvoiceList } from '../components/InvoiceList.jsx';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { useBillingAction, useInvoices } from '../hooks/useBillingActions.js';
import { errorReason } from '../api/billingApi.js';
import { getUpgradeRecommendation } from '../utils/subscriptionRecommendations.js';
import { formatMoney } from '../utils/money.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || '';
const KNOWN_ERRORS = new Set([
  'payments_not_configured', 'price_not_synced', 'subscription_exists', 'plan_not_available', 'contact_sales',
  'no_billing_account', 'no_subscription', 'payment_required', 'cancellation_pending', 'already_on_plan',
  'downgrade_scheduled', 'already_scheduled', 'already_cancelling', 'not_cancelling', 'provider_error',
]);

export function PlansSubscriptionPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const [searchParams, setSearchParams] = useSearchParams();
  const checkoutResult = searchParams.get('checkout');
  const plansQuery = usePlans();
  // After returning from Stripe the webhook usually lands within seconds:
  // poll briefly so the new plan shows without a manual reload.
  const subscriptionQuery = useSubscription(companyId, { refetchInterval: checkoutResult === 'success' ? 3000 : false });
  const subscription = subscriptionQuery.data;
  const invoicesQuery = useInvoices(Boolean(subscription?.canManageBilling && subscription?.hasBillingAccount));
  const checkout = useBillingAction('checkout');
  const changePlan = useBillingAction('changePlan');
  const portal = useBillingAction('openPortal');
  const cancel = useBillingAction('cancel');
  const resume = useBillingAction('resume');
  const cancelScheduled = useBillingAction('cancelScheduledChange');
  const [billingPeriod, setBillingPeriod] = useState('monthly');
  const [confirm, setConfirm] = useState(null);
  const [notice, setNotice] = useState(null);
  const compareRef = useRef(null);
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const formatDate = (value) => dateFormatter.format(new Date(value));

  useEffect(() => {
    if (subscription?.hasSubscription && subscription.billingPeriod) setBillingPeriod(subscription.billingPeriod);
  }, [subscription?.hasSubscription, subscription?.billingPeriod]);
  useEffect(() => {
    if (checkoutResult === 'success') setNotice({ variant: 'success', message: t('billing.checkout.success') });
    if (checkoutResult === 'cancelled') setNotice({ variant: 'info', message: t('billing.checkout.cancelled') });
    if (checkoutResult) {
      const timer = window.setTimeout(() => setSearchParams({}, { replace: true }), 30000);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [checkoutResult, setSearchParams, t]);

  if (plansQuery.isPending || subscriptionQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="78px" variant="rectangular" /><Skeleton height="190px" variant="rectangular" /><div>{[0, 1, 2].map((item) => <Skeleton key={item} height="150px" variant="rectangular" />)}</div></div>;
  if (plansQuery.isError || subscriptionQuery.isError) return <EmptyState title={t('billing.management.errorTitle')} description={t('billing.management.errorDescription')} action={<Button size="sm" onClick={() => { plansQuery.refetch(); subscriptionQuery.refetch(); }}>{t('billing.management.retry')}</Button>} />;

  const plans = plansQuery.data.plans;
  const paymentsEnabled = plansQuery.data.paymentsEnabled;
  const currentPlan = plans.find((plan) => plan.id === subscription.planId)
    || { id: subscription.planId, name: { en: subscription.planName, ar: subscription.planName }, limits: subscription.limits || {}, prices: {}, selfServe: false };
  const canManage = subscription.canManageBilling;
  const busy = checkout.isPending || changePlan.isPending || portal.isPending || cancel.isPending || resume.isPending || cancelScheduled.isPending;

  const fail = (error) => {
    const reason = errorReason(error);
    setNotice({ variant: 'error', message: t(`billing.errors.${KNOWN_ERRORS.has(reason) ? reason : 'generic'}`) });
  };
  const run = (mutation, payload, successKey) => mutation.mutate(payload, {
    onSuccess: (result) => { if (successKey && !result?.url) setNotice({ variant: 'success', message: t(successKey, { date: result?.effective_at ? formatDate(result.effective_at) : '' }) }); },
    onError: fail,
  });

  const recommendation = (() => {
    const raw = getUpgradeRecommendation(subscription, searchParams.get('reason'));
    if (!raw) return null;
    return {
      titleKey: raw.contextual ? `billing.management.context.${raw.key}.title` : `billing.management.recommendation.${raw.type}Title`,
      descriptionKey: raw.contextual ? `billing.management.context.${raw.key}.description` : `billing.management.recommendation.${raw.type}Description`,
      values: raw.key ? { metric: t(`billing.management.usageLabels.${raw.key}`), used: numberFormatter.format(subscription.usage[raw.key]), limit: numberFormatter.format(subscription.limits[raw.key]) } : {},
    };
  })();

  const planAction = (plan) => {
    const isCurrent = plan.id === currentPlan.id && (!subscription.hasSubscription || billingPeriod === subscription.billingPeriod);
    if (!plan.selfServe) return { label: t('billing.management.contactSales'), disabled: !SUPPORT_EMAIL, hint: SUPPORT_EMAIL ? null : t('billing.management.contactTeam'), onAction: () => { window.location.href = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('KEEL Custom plan')}`; } };
    if (!canManage) return { label: isCurrent && subscription.hasSubscription ? t('billing.management.currentPlan') : t('billing.management.askOwner'), disabled: true };
    if (!paymentsEnabled) return { label: t('billing.management.paymentsUnavailable'), disabled: true };
    if (!plan.prices?.[billingPeriod]?.purchasable) return { label: t('billing.management.notAvailable'), disabled: true };
    if (subscription.hasSubscription) {
      if (isCurrent) return { label: t('billing.management.currentPlan'), disabled: true };
      return { label: t('billing.management.switchPlan'), onAction: () => setConfirm({ plan, period: billingPeriod }) };
    }
    return { label: subscription.status === 'trial' ? t('billing.management.subscribeKeepTrial') : t('billing.management.subscribe'),
      onAction: () => run(checkout, { planId: plan.id, billingPeriod }) };
  };

  const currentActions = canManage && subscription.hasBillingAccount && paymentsEnabled ? <>
    <Button size="sm" variant="outline" loading={portal.isPending} disabled={busy} onClick={() => run(portal)}>{t('billing.management.manageBilling')}</Button>
    {subscription.hasSubscription && (subscription.cancelAtPeriodEnd
      ? <Button size="sm" loading={resume.isPending} disabled={busy} onClick={() => run(resume, undefined, 'billing.management.resumed')}>{t('billing.management.resume')}</Button>
      : <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirm({ cancel: true })}>{t('billing.management.cancel')}</Button>)}
  </> : null;

  const confirmPrice = confirm?.plan?.prices?.[confirm.period];
  return <div className="billing-management-page" dir={dir}>
    <PageHeader title={t('billing.management.title')} subtitle={t('billing.management.subtitle')} />
    {!paymentsEnabled && <div className="billing-provider-note" role="note">{t('billing.management.paymentsUnavailableHint')}</div>}
    <CurrentPlanCard subscription={subscription} plan={currentPlan} locale={locale} t={t} formatDate={formatDate} actions={currentActions} />
    {subscription.scheduledChange && <div className="billing-provider-note" role="status">
      <span>{t('billing.management.scheduledChange', { plan: plans.find((p) => p.id === subscription.scheduledChange.planId)?.name?.[locale] || subscription.scheduledChange.planId, date: subscription.scheduledChange.effectiveAt ? formatDate(subscription.scheduledChange.effectiveAt) : '' })}</span>
      {canManage && <Button size="sm" variant="ghost" loading={cancelScheduled.isPending} onClick={() => run(cancelScheduled, undefined, 'billing.management.scheduledCancelled')}>{t('billing.management.keepCurrentPlan')}</Button>}
    </div>}
    {['failed', 'expired'].includes(subscription.status) && <div className="billing-provider-note is-warning" role="alert">{t(`billing.management.statusHelp.${subscription.status}`)}</div>}

    <section className="billing-management-section" aria-labelledby="usage-title"><header><h2 id="usage-title">{t('billing.management.usageTitle')}</h2><p>{t('billing.management.usageSubtitle')}</p></header><UsageLimitGrid usage={subscription.usage} limits={subscription.limits} locale={locale} t={t} /></section>
    <UpgradeRecommendation recommendation={recommendation} onCompare={() => compareRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} t={t} />

    <section ref={compareRef} className="billing-management-section billing-compare-section" aria-labelledby="compare-title">
      <header className="billing-compare-header"><div><h2 id="compare-title">{t('billing.management.compareTitle')}</h2><p>{t('billing.management.compareSubtitle')}</p></div><PeriodSelector plans={plans} value={billingPeriod} onChange={setBillingPeriod} name="in-app-billing-period" /></header>
      <div className="ceopro-plan-grid billing-management-plans">{plans.map((plan) => {
        const action = planAction(plan);
        return <PlanCard key={plan.id} plan={plan} billingPeriod={billingPeriod} currentPlan={plan.id === currentPlan.id} onAction={action.onAction} actionLabel={action.label} actionDisabled={action.disabled || busy} actionHint={action.hint} />;
      })}</div>
    </section>

    <section className="billing-management-section" aria-labelledby="comparison-title"><header><h2 id="comparison-title">{t('billing.management.comparison.title')}</h2><p>{t('billing.management.comparison.subtitle')}</p></header><PlanComparisonTable plans={plans} currentPlanId={currentPlan.id} /></section>
    {canManage && subscription.hasBillingAccount && <section className="billing-management-section" aria-labelledby="invoices-title"><header><h2 id="invoices-title">{t('billing.invoices.title')}</h2></header>{invoicesQuery.isPending ? <Skeleton height="80px" /> : <InvoiceList invoices={invoicesQuery.data} locale={locale} t={t} formatDate={formatDate} />}</section>}

    <Modal isOpen={Boolean(confirm)} onClose={() => setConfirm(null)} title={confirm?.cancel ? t('billing.management.cancelTitle') : t('billing.management.switchTitle')}>
      {confirm?.cancel
        ? <p>{t('billing.management.cancelBody', { date: subscription.renewsAt ? formatDate(subscription.renewsAt) : '' })}</p>
        : confirm && <p>{t('billing.management.switchBody', { plan: confirm.plan.name?.[locale] || confirm.plan.name?.en, price: confirmPrice ? formatMoney(confirmPrice.amount, confirmPrice.currency, locale) : '' })}</p>}
      <div className="billing-modal-actions">
        <Button variant="outline" onClick={() => setConfirm(null)}>{t('billing.management.back')}</Button>
        <Button variant="primary" loading={busy} onClick={() => {
          const current = confirm;
          setConfirm(null);
          if (current.cancel) run(cancel, undefined, 'billing.management.cancelled');
          else run(changePlan, { planId: current.plan.id, billingPeriod: current.period }, 'billing.management.changed');
        }}>{confirm?.cancel ? t('billing.management.confirmCancel') : t('billing.management.confirmSwitch')}</Button>
      </div>
    </Modal>
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
  </div>;
}
