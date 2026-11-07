import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { billingErrorMessage, errorReason } from '../api/billingApi.js';
import { PlanSummaryCard } from '../components/PlanSummaryCard.jsx';
import { toOriginalPlan } from '../api/originalBillingModel.js';
import { CouponInput } from '../components/CouponInput.jsx';
import { OnboardingPageShell } from '../../onboarding/components/OnboardingPageShell.jsx';
import { StripePaymentMethod } from '../components/StripePaymentMethod.jsx';
import { useBillingAction } from '../hooks/useBillingActions.js';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { canStartPlanTrial } from '../utils/onboardingRouting.js';
import { saveOnboardingPlan } from '../../onboarding/store/onboardingStore.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
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
  const cancelPending = useBillingAction('cancelPendingCheckout');
  const [errorMessage, setErrorMessage] = useState('');
  const [pendingConflict, setPendingConflict] = useState(false);
  const [promoCode,setPromoCode]=useState('');
  const [trialPending, setTrialPending] = useState(false);
  const planId = searchParams.get('plan');
  const billingPeriod = searchParams.get('period');
  const plan = plansQuery.data?.plans.find((item) => item.id === planId);
  const price = plan?.prices?.[billingPeriod];
  const paymentsEnabled = Boolean(plansQuery.data?.paymentsEnabled);
  const trialAvailable = canStartPlanTrial(subscriptionQuery.data, plan);
  const canCheckout = Boolean(plan?.selfServe && price?.purchasable && paymentsEnabled);
  const busy = trialPending || checkout.isPending || cancelPending.isPending;
  const showError = (error) => {
    setPendingConflict(errorReason(error) === 'checkout_pending');
    setErrorMessage(billingErrorMessage(error, t));
  };

  useEffect(() => {
    if (plansQuery.isPending || subscriptionQuery.isPending || plansQuery.isError || subscriptionQuery.isError) return;
    const validPeriod = plan?.prices?.[billingPeriod];
    if (!plan?.selfServe || (!validPeriod?.purchasable && !canStartPlanTrial(subscriptionQuery.data, plan))) {
      navigate(routePaths.onboardingPlan, { replace: true });
    }
  }, [billingPeriod, navigate, plan, plansQuery.isPending, plansQuery.isError, subscriptionQuery.data, subscriptionQuery.isPending, subscriptionQuery.isError]);

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
    setPendingConflict(false);
    sessionStorage.setItem('keel.onboarding.checkoutPending', '1');
    try {
      const result = await checkout.mutateAsync({ planId, billingPeriod, promotionCode:promoCode.trim()||undefined });
      if (!result?.url) throw new Error('Checkout URL was not returned by the billing service.');
    } catch (error) {
      sessionStorage.removeItem('keel.onboarding.checkoutPending');
      showError(error);
    }
  };

  const beginTrial = async () => {
    setErrorMessage('');
    setPendingConflict(false);
    setTrialPending(true);
    try {
      await saveOnboardingPlan(planId, billingPeriod);
      sessionStorage.setItem('keel.onboarding.checkoutPending', '1');
      const result=await startTrial.mutateAsync({ planId, billingPeriod, promotionCode:promoCode.trim()||undefined });
      if(!result?.url)throw new Error(t('billing.errors.generic'));
    } catch (error) {
      sessionStorage.removeItem('keel.onboarding.checkoutPending');
      showError(error);
    } finally {
      setTrialPending(false);
    }
  };

  return (
    <OnboardingPageShell wide showProgress={false}>
      <header className="ceopro-payment-heading"><Link to={routePaths.onboardingPlan}>{t('billing.payment.backToPlans')}</Link><h1>{t('billing.payment.title')}</h1></header>
      <div className="ceopro-payment-layout ceopro-payment-layout--focused">
        <PlanSummaryCard
          selected
          trialAvailable={trialAvailable}
          promotionEntered={Boolean(promoCode.trim())}
          plan={toOriginalPlan(plan)}
          billingPeriod={billingPeriod}
          checkoutTrialEndsAt={subscriptionQuery.data.checkoutTrialEndsAt}
          checkoutMode={subscriptionQuery.data.checkoutTrialEndsAt ? 'trial' : 'paid'}
          changePlanAction={<Link className="ceopro-payment-change-plan" to={routePaths.onboardingPlan}>{t('billing.payment.changePlan')}</Link>}
        >
          <section className="ceopro-payment-method ceopro-payment-method--single" aria-label={t('billing.payment.methodLabel')}>
          {errorMessage && <div className="billing-provider-note is-warning" role="alert">{errorMessage}</div>}
          {pendingConflict && <Button variant="outline" disabled={busy} onClick={async () => {
            try {
              await cancelPending.mutateAsync();
              setPendingConflict(false);
              setErrorMessage(t('billing.returnState.closed'));
            } catch (error) { showError(error); }
          }}>{t('billing.returnState.closeCheckout')}</Button>}
          <p className="ceopro-payment-required">{t('billing.payment.paymentMethodRequired')}</p>
          <Button
            variant="primary"
            fullWidth
            loading={trialPending || checkout.isPending}
            loadingLabel={t('billing.onboarding.processing')}
            disabled={!canCheckout || busy}
            onClick={trialAvailable ? beginTrial : continueToStripe}
          >
            {trialAvailable ? t('billing.onboarding.startTrial', { days: plan.trialDays }) : t('billing.payment.continueSecureCheckout')}
          </Button>
          {(trialAvailable || subscriptionQuery.data.checkoutTrialEndsAt) && <p className="ceopro-payment-no-charge">{t('billing.payment.noChargeUntilTrialEnd')}</p>}
          <StripePaymentMethod />
          <div className="ceopro-payment-promo">
            <CouponInput planId={planId} billingPeriod={billingPeriod} value={promoCode} onChange={setPromoCode} disabled={busy}/>
          </div>
          {!paymentsEnabled && <div className="billing-provider-note" role="note">{t('billing.management.paymentsUnavailableHint')}</div>}
          {!price?.purchasable && paymentsEnabled && <div className="billing-provider-note" role="note">{t('billing.onboarding.planUnavailable')}</div>}
          </section>
        </PlanSummaryCard>
      </div>
    </OnboardingPageShell>
  );
}
