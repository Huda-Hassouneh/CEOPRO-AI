import { ArrowLeft, ArrowRight, LockKeyhole } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { BILLING_PERIODS, formatPreviewUsd, getBillingPeriod, getPreviewPlanPrice } from '../config/billingPreviewData.js';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { useUpgradeCheckout } from '../hooks/useUpgradeCheckout.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

export function BillingCheckoutPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const [params] = useSearchParams();
  const plansQuery = usePlans();
  const subscriptionQuery = useSubscription(companyId);
  const checkout = useUpgradeCheckout();
  const [notice, setNotice] = useState(null);
  const selectedPlanId = params.get('plan');
  const requestedPeriod = params.get('period');
  const validPeriod = BILLING_PERIODS.some((period) => period.value === requestedPeriod) ? requestedPeriod : null;
  const period = validPeriod ? getBillingPeriod(validPeriod, selectedPlanId) : null;
  const plans = plansQuery.data?.plans || [];
  const subscription = subscriptionQuery.data;
  const currentPlan = plans.find((plan) => plan.id === subscription?.planId);
  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId);
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);

  if (plansQuery.isPending || subscriptionQuery.isPending) return <div className="billing-checkout-loading" aria-busy="true"><Skeleton height="82px" variant="rectangular" /><Skeleton height="360px" variant="rectangular" /></div>;
  if (plansQuery.isError || subscriptionQuery.isError) return <EmptyState title={t('billing.checkoutInApp.errorTitle')} description={t('billing.checkoutInApp.errorDescription')} action={<Button onClick={() => { plansQuery.refetch(); subscriptionQuery.refetch(); }}>{t('billing.management.retry')}</Button>} />;

  const invalid = !subscription || !currentPlan || !selectedPlan || !period || selectedPlan.status !== 'active' || !selectedPlan.billingOptions?.includes(validPeriod) || selectedPlan.id === 'custom' || (selectedPlan.id === currentPlan.id && subscription.status !== 'trial');
  if (invalid) return <EmptyState title={t('billing.checkoutInApp.invalidTitle')} description={t('billing.checkoutInApp.invalidDescription')} action={<Link className="billing-link-button" to={routePaths.billing}>{t('billing.checkoutInApp.backToBilling')}</Link>} />;

  const pricing = getPreviewPlanPrice(selectedPlan.id, validPeriod);
  const currentPricing = getPreviewPlanPrice(currentPlan.id, subscription.billingPeriod);
  const beginCheckout = async () => {
    try {
      const result = await checkout.mutateAsync({ companyId, currentPlanId: currentPlan.id, newPlanId: selectedPlan.id, billingPeriod: validPeriod });
      if (!result?.available || !result.success) {
        setNotice({ variant: 'info', message: t('billing.checkoutInApp.paymentUnavailable') });
        return;
      }
    } catch {
      setNotice({ variant: 'error', message: t('billing.checkoutInApp.upgradeFailed') });
    }
  };

  return <div className="billing-checkout-page" dir={dir}>
    <Link className="billing-back-link" to={routePaths.billing}><ArrowLeft className="ceopro-setup-direction-icon" size={15} />{t('billing.checkoutInApp.backToBilling')}</Link>
    <PageHeader title={t('billing.checkoutInApp.title')} subtitle={t('billing.checkoutInApp.subtitle')} />
    <div className="billing-checkout-layout">
      <Card className="billing-upgrade-review">
        <h2>{t('billing.checkoutInApp.summaryTitle')}</h2>
        <dl>
          <div><dt>{t('billing.checkoutInApp.currentPlan')}</dt><dd>{currentPlan.name?.[locale] || t(currentPlan.nameKey)}{currentPricing && <small>{formatPreviewUsd(currentPricing.total, locale)}</small>}</dd></div>
          <div><dt>{t('billing.checkoutInApp.newPlan')}</dt><dd>{selectedPlan.name?.[locale] || t(selectedPlan.nameKey)}</dd></div>
          <div><dt>{t('billing.checkoutInApp.billingPeriod')}</dt><dd>{period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months })}</dd></div>
          {pricing && <div><dt>{t('billing.checkoutInApp.configuredPrice')}</dt><dd>{formatPreviewUsd(pricing.total, locale)}<small>{subscription.currency}</small></dd></div>}
          {subscription.renewsAt && <div><dt>{t('billing.checkoutInApp.currentRenewal')}</dt><dd>{dateFormatter.format(new Date(subscription.renewsAt))}</dd></div>}
          <div><dt>{t('billing.checkoutInApp.effectiveDate')}</dt><dd>{t('billing.checkoutInApp.providerDetermined')}</dd></div>
        </dl>
      </Card>
      <aside className="billing-payment-boundary"><span><LockKeyhole size={24} /></span><h2>{t('billing.checkoutInApp.securePayment')}</h2><p>{t('billing.checkoutInApp.securePaymentDescription')}</p><Button fullWidth trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={15} />} loading={checkout.isPending} loadingLabel={t('billing.checkoutInApp.preparing')} onClick={beginCheckout}>{t('billing.checkoutInApp.continue')}</Button><small>{t('billing.checkoutInApp.noPaymentStored')}</small></aside>
    </div>
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
  </div>;
}
