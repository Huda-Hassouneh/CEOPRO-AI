import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { PlanCard } from '../components/PlanCard.jsx';
import { CustomPlanCard } from '../components/CustomPlanCard.jsx';
import { PeriodSelector } from '../components/PeriodSelector.jsx';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { getOnboardingReturnPath, getPostSetupPath, hasActivePlanAccess } from '../utils/onboardingRouting.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

const EMPTY_PLANS = [];

export function OnboardingPlanSelectionPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const companyId = useAuthStore((state) => state.tenantId);
  const plansQuery = usePlans();
  const subscriptionQuery = useSubscription(companyId);
  const plans = plansQuery.data?.plans || EMPTY_PLANS;
  const [billingPeriod, setBillingPeriod] = useState('monthly');

  const periods = useMemo(
    () => ['monthly', 'three-months', 'six-months'].filter((period) => plans.some((plan) => plan.prices?.[period])),
    [plans],
  );

  useEffect(() => {
    if (periods.length && !periods.includes(billingPeriod)) setBillingPeriod(periods[0]);
  }, [billingPeriod, periods]);

  useEffect(() => {
    const subscription = subscriptionQuery.data;
    if (hasActivePlanAccess(subscription)) {
      const destination = getOnboardingReturnPath();
      sessionStorage.removeItem('keel.onboarding.returnPath');
      navigate(destination, { replace: true });
    } else if (subscription?.hasSubscription) {
      navigate(getPostSetupPath(subscription), { replace: true });
    }
  }, [navigate, subscriptionQuery.data]);

  const selectPlan = (plan) => {
    const price = plan.prices?.[billingPeriod];
    const trialAvailable = subscriptionQuery.data?.trialAvailable && plan.trialDays > 0;
    if (!plan.selfServe || (!trialAvailable && (!plansQuery.data?.paymentsEnabled || !price?.purchasable))) return;
    const query = new URLSearchParams({ plan: plan.id, period: billingPeriod });
    navigate(`${routePaths.onboardingPlanPayment}?${query.toString()}`);
  };

  if (plansQuery.isPending || subscriptionQuery.isPending) {
    return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="64px" /><Skeleton height="260px" /></div>;
  }

  if (plansQuery.isError || subscriptionQuery.isError) {
    return <EmptyState
      title={t('billing.management.errorTitle')}
      description={t('billing.management.errorDescription')}
      action={<Button onClick={() => { plansQuery.refetch(); subscriptionQuery.refetch(); }}>{t('billing.management.retry')}</Button>}
    />;
  }

  const selectablePlans = plans.filter((plan) => plan.selfServe);
  return (
    <div className="billing-management-page">
      <PageHeader title={t('billing.onboarding.chooseTitle')} subtitle={t('billing.onboarding.chooseSubtitle')} />
      {!plansQuery.data.paymentsEnabled && (
        <div className="billing-provider-note" role="note">{t('billing.management.paymentsUnavailableHint')}</div>
      )}
      <section className="billing-management-section" aria-labelledby="onboarding-plan-title">
        <header className="billing-compare-header">
          <div><h2 id="onboarding-plan-title">{t('billing.management.compareTitle')}</h2><p>{t('billing.management.compareSubtitle')}</p></div>
          {periods.length > 0 && <PeriodSelector plans={plans} value={billingPeriod} onChange={setBillingPeriod} name="onboarding-billing-period" />}
        </header>
        <div className="ceopro-plan-grid billing-management-plans custom-plan-grid">
          {selectablePlans.map((plan) => {
            const trialAvailable = subscriptionQuery.data.trialAvailable && plan.trialDays > 0;
            const price = plan.prices?.[billingPeriod];
            const enabled = Boolean(plan.selfServe && (trialAvailable || (plansQuery.data.paymentsEnabled && price?.purchasable)));
            return <PlanCard
              key={plan.id}
              plan={plan}
              billingPeriod={billingPeriod}
              onAction={() => selectPlan(plan)}
              actionLabel={t('billing.onboarding.selectPlan')}
              actionDisabled={!enabled}
              actionHint={!enabled && plan.selfServe ? t('billing.onboarding.planUnavailable') : undefined}
            />;
          })}
          <CustomPlanCard returnTo={routePaths.onboardingPlan} />
        </div>
      </section>
    </div>
  );
}
