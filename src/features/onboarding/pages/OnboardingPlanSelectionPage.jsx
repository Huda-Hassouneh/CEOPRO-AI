import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useSWR from 'swr';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { billingApi } from '../../billing/api/billingApi.js';
import { PlanSelector } from '../../billing/components/PlanSelector.jsx';
import { StandardPlanRecommendation } from '../../billing/components/StandardPlanRecommendation.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

export function OnboardingPlanSelectionPage() {
  const navigate = useNavigate();
  const { t, locale } = useI18n();
  const { data: response, error, isLoading } = useSWR(
    'subscription-plans',
    billingApi.getPlans,
    swrOptions,
  );

  const plans = useMemo(() => {
    const rawPlans = response?.data ?? [];
    return [...rawPlans]
      .filter((plan) => plan?.isActive !== false)
      .sort((a, b) => (a.tier_level || 0) - (b.tier_level || 0))
      .map((plan) => ({
        ...plan,
        displayName: locale === 'ar' && plan.name_ar ? plan.name_ar : plan.name,
        displayDescription:
          locale === 'ar' && plan.description_ar ? plan.description_ar : plan.description,
      }));
  }, [response, locale]);

  const selectedPlan = useOnboardingStore((state) => state.selectedPlan);
  const standardRecommendationResolved = useOnboardingStore(
    (state) => state.standardRecommendationResolved,
  );
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const selectPlan = useOnboardingStore((state) => state.selectPlan);
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const setBillingPeriod = useOnboardingStore((state) => state.setBillingPeriod);
  const resolveStandardRecommendation = useOnboardingStore(
    (state) => state.resolveStandardRecommendation,
  );
  const [showRecommendation, setShowRecommendation] = useState(false);

  useEffect(() => {
    if (isLoading || !plans.length) return;

    const supportedPeriods = plans.flatMap((plan) => plan.pricingOptions ?? []);
    if (!billingPeriod || !supportedPeriods.some((option) => option.period === billingPeriod)) {
      const firstPeriod = supportedPeriods[0]?.period;
      if (firstPeriod) setBillingPeriod(firstPeriod);
    }

    if (selectedPlan !== 'custom' && !plans.some((plan) => plan.id === selectedPlan)) {
      selectPlan(plans[1]?.id || plans[0]?.id || '');
    }
  }, [plans, isLoading, billingPeriod, selectedPlan, setBillingPeriod, selectPlan]);

  const goToPayment = (planId) => {
    const plan = plans.find((item) => item.id === planId);
    if (!plan) return;
    const checkoutMode = Number(plan.trialPeriodValue) > 0 ? 'trial' : 'paid';
    setPlanChoice(planId, checkoutMode);
    navigate(routePaths.onboardingPlanPayment);
  };

  const handleContinue = () => {
    if (selectedPlan === 'custom') {
      setPlanChoice('custom', 'paid');
      navigate(routePaths.onboardingPlanCustom);
      return;
    }
    const plan = plans.find((item) => item.id === selectedPlan);
    if (!plan) return;

    const lowestTierPlan = plans[0];
    const middleTierPlan = plans[1];
    if (
      selectedPlan === lowestTierPlan?.id &&
      !standardRecommendationResolved &&
      middleTierPlan?.isActive !== false &&
      Number(middleTierPlan?.trialPeriodValue) > 0
    ) {
      setShowRecommendation(true);
      return;
    }

    goToPayment(selectedPlan);
  };

  const resolveRecommendation = (planId) => {
    resolveStandardRecommendation();
    setShowRecommendation(false);
    goToPayment(planId);
  };

  const selectedPlanData = selectedPlan === 'custom' ? { id: 'custom', isActive: true, pricingOptions: [{ period: billingPeriod }] } : plans.find((plan) => plan.id === selectedPlan);
  const isContinueDisabled =
    isLoading ||
    Boolean(error) ||
    !selectedPlanData ||
    selectedPlanData.isActive === false ||
    !selectedPlanData.pricingOptions?.some((option) => option.period === billingPeriod);
  const recommendedTrialDays = Number(plans[1]?.trialPeriodValue || 0);

  return (
    <OnboardingPageShell
      step={5}
      title={t('billing.choose.title')}
      subtitle={t('billing.choose.subtitle')}
    >
      {isLoading ? (
        <Skeleton height="400px" variant="rectangular" />
      ) : error ? (
        <p
          style={{
            color: 'var(--color-danger, red)',
            textAlign: 'center',
            padding: '2rem',
          }}
        >
          {t('billing.management.loadError') || 'Failed to load subscription plans.'}
        </p>
      ) : (
        <PlanSelector
          plans={plans}
          selectedPlan={selectedPlan}
          billingPeriod={billingPeriod || 'monthly'}
          onPeriodChange={setBillingPeriod}
          onPlanSelect={selectPlan}
          onBuildCustom={() => selectPlan('custom')}
          showCustomPlan
        />
      )}

      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingObjectives)}
        onContinue={handleContinue}
        disabled={isContinueDisabled}
      />

      <StandardPlanRecommendation
        open={showRecommendation}
        onClose={() => setShowRecommendation(false)}
        trialDays={recommendedTrialDays}
        onTryPro={() => resolveRecommendation(plans[1]?.id)}
        onContinueStandard={() => resolveRecommendation(plans[0]?.id)}
      />
    </OnboardingPageShell>
  );
}
