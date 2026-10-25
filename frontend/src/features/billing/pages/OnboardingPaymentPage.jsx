import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { billingApi, errorReason } from '../api/billingApi.js';
import { PlanCard } from '../components/PlanCard.jsx';
import { StripePaymentMethod } from '../components/StripePaymentMethod.jsx';
import { useBillingAction } from '../hooks/useBillingActions.js';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { getOnboardingReturnPath, getPostSetupPath, hasActivePlanAccess } from '../utils/onboardingRouting.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

export function OnboardingPaymentPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const companyId = useAuthStore((state) => state.tenantId);
  const plansQuery = usePlans();
  const subscriptionQuery = useSubscription(companyId);
  const checkout = useBillingAction('checkout');
  const startTrial = useBillingAction('startTrial');
  const [errorMessage, setErrorMessage] = useState('');
  const [trialPending, setTrialPending] = useState(false);
  const planId = searchParams.get('plan');
  const billingPeriod = searchParams.get('period');
  const plan = plansQuery.data?.plans.find((item) => item.id === planId);
  const price = plan?.prices?.[billingPeriod];
  const paymentsEnabled = Boolean(plansQuery.data?.paymentsEnabled);
  const trialAvailable = Boolean(subscriptionQuery.data?.trialAvailable && plan?.trialDays > 0);
  const canCheckout = Boolean(plan?.selfServe && price?.purchasable && paymentsEnabled);

  useEffect(() => {
    if (hasActivePlanAccess(subscriptionQuery.data)) {
      const destination = getOnboardingReturnPath();
      sessionStorage.removeItem('keel.onboarding.returnPath');
      navigate(destination, { replace: true });
    } else if (subscriptionQuery.data?.hasSubscription) {
      navigate(getPostSetupPath(subscriptionQuery.data), { replace: true });
    }
  }, [navigate, subscriptionQuery.data]);

  useEffect(() => {
    if (plansQuery.isPending || subscriptionQuery.isPending) return;
    const validPeriod = plan?.prices?.[billingPeriod];
    if (!plan?.selfServe || (!validPeriod?.purchasable && !(subscriptionQuery.data?.trialAvailable && plan.trialDays > 0))) {
      navigate(routePaths.onboardingPlan, { replace: true });
    }
  }, [billingPeriod, navigate, plan, plansQuery.isPending, subscriptionQuery.data, subscriptionQuery.isPending]);

  if (plansQuery.isPending || subscriptionQuery.isPending) {
    return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="260px" /></div>;
  }

  if (plansQuery.isError || subscriptionQuery.isError || !plan) {
    return <EmptyState
      title={t('billing.management.errorTitle')}
      description={t('billing.management.errorDescription')}
      action={<Button onClick={() => navigate(routePaths.onboardingPlan)}>{t('billing.onboarding.backToPlans')}</Button>}
    />;
  }

  const continueToStripe = async () => {
    setErrorMessage('');
    sessionStorage.setItem('keel.onboarding.checkoutPending', '1');
    try {
      const result = await checkout.mutateAsync({ planId, billingPeriod });
      if (!result?.url) throw new Error('Checkout URL was not returned by the billing service.');
    } catch (error) {
      sessionStorage.removeItem('keel.onboarding.checkoutPending');
      const reason = errorReason(error);
      setErrorMessage(reason ? t(`billing.errors.${reason}`) : (error?.response?.data?.detail?.message || t('billing.errors.generic')));
    }
  };

  const beginTrial = async () => {
    setErrorMessage('');
    setTrialPending(true);
    try {
      await startTrial.mutateAsync({ planId });
      const refreshed = await billingApi.getSubscription();
      if (hasActivePlanAccess(refreshed)) {
        sessionStorage.removeItem('keel.onboarding.checkoutPending');
        const destination = getOnboardingReturnPath();
        sessionStorage.removeItem('keel.onboarding.returnPath');
        navigate(destination, { replace: true });
      } else {
        setErrorMessage(t('billing.onboarding.activationPending'));
      }
    } catch (error) {
      const reason = errorReason(error);
      setErrorMessage(reason ? t(`billing.errors.${reason}`) : (error?.response?.data?.detail?.message || t('billing.errors.generic')));
    } finally {
      setTrialPending(false);
    }
  };

  return (
    <div className="billing-management-page">
      <PageHeader title={t('billing.onboarding.paymentTitle')} subtitle={t('billing.onboarding.paymentSubtitle')} />
      <div className="billing-checkout-layout">
        <div>
          {errorMessage && <div className="billing-provider-note is-warning" role="alert">{errorMessage}</div>}
          {trialAvailable && <section className="billing-payment-boundary">
            <h2>{t('billing.onboarding.trialTitle', { days: plan.trialDays })}</h2>
            <p>{t('billing.onboarding.trialDescription')}</p>
            <Button variant="outline" loading={trialPending} onClick={beginTrial}>
              {t('billing.onboarding.startTrial', { days: plan.trialDays })}
            </Button>
          </section>}
          <StripePaymentMethod
            onContinue={continueToStripe}
            loading={checkout.isPending}
            disabled={!canCheckout}
          />
          {!paymentsEnabled && <div className="billing-provider-note" role="note">{t('billing.management.paymentsUnavailableHint')}</div>}
          {!price?.purchasable && paymentsEnabled && <div className="billing-provider-note" role="note">{t('billing.onboarding.planUnavailable')}</div>}
          <Link className="billing-link-button" to={routePaths.onboardingPlan}>{t('billing.onboarding.backToPlans')}</Link>
        </div>
        <div className="billing-management-section">
          <PlanCard plan={plan} billingPeriod={billingPeriod} />
        </div>
      </div>
    </div>
  );
}
