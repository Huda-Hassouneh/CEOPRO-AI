import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { PlanSelector } from '../../billing/components/PlanSelector.jsx';
import { StandardPlanRecommendation } from '../../billing/components/StandardPlanRecommendation.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';
import { getPreviewPlan } from '../../billing/config/billingPreviewData.js';

export function OnboardingPlanSelectionPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const selectedPlan = useOnboardingStore((state) => state.selectedPlan);
  const standardRecommendationResolved = useOnboardingStore((state) => state.standardRecommendationResolved);
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const selectPlan = useOnboardingStore((state) => state.selectPlan);
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const resolveStandardRecommendation = useOnboardingStore((state) => state.resolveStandardRecommendation);
  const setBillingPeriod = useOnboardingStore((state) => state.setBillingPeriod);
  const [showRecommendation, setShowRecommendation] = useState(false);

  const goToPayment = (plan, mode) => {
    if (getPreviewPlan(plan).status !== 'active' || !getPreviewPlan(plan).billingOptions.includes(billingPeriod)) return;
    if (plan === 'custom') {
      selectPlan('custom');
      navigate(routePaths.onboardingPlanCustom);
      return;
    }
    setPlanChoice(plan, mode);
    navigate(routePaths.onboardingPlanPayment);
  };

  const choosePlan = (plan) => {
    if (plan === 'standard' && !standardRecommendationResolved && getPreviewPlan('pro').status === 'active' && getPreviewPlan('pro').trialDays > 0) {
      selectPlan('standard');
      setShowRecommendation(true);
      return;
    }
    goToPayment(plan, getPreviewPlan(plan).trialDays > 0 ? 'trial' : 'paid');
  };

  const resolveRecommendation = (plan, mode) => {
    resolveStandardRecommendation();
    setShowRecommendation(false);
    goToPayment(plan, mode);
  };

  return (
    <OnboardingPageShell step={5} title={t('billing.choose.title')} subtitle={t('billing.choose.subtitle')}>
      <PlanSelector
        selectedPlan={selectedPlan}
        billingPeriod={billingPeriod}
        onPlanSelect={choosePlan}
        onPeriodChange={setBillingPeriod}
        onBuildCustom={() => choosePlan('custom')}
      />
      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingObjectives)}
        onContinue={() => goToPayment(selectedPlan || 'pro', 'trial')}
        disabled={getPreviewPlan(selectedPlan || 'pro').status !== 'active' || !getPreviewPlan(selectedPlan || 'pro').billingOptions.includes(billingPeriod)}
      />
      <StandardPlanRecommendation
        open={showRecommendation}
        onClose={() => setShowRecommendation(false)}
        onTryPro={() => resolveRecommendation('pro', 'trial')}
        onContinueStandard={() => resolveRecommendation('standard', 'paid')}
      />
    </OnboardingPageShell>
  );
}
