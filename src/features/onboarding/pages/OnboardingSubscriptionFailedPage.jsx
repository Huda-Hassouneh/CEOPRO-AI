import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { SubscriptionResult } from '../../billing/components/SubscriptionResult.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingSubscriptionFailedPage() {
  const navigate = useNavigate();
  const selectedPlan = useOnboardingStore((state) => state.selectedPlan);
  const checkoutMode = useOnboardingStore((state) => state.checkoutMode);
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  return (
    <OnboardingPageShell wide showProgress={false}>
      <SubscriptionResult planId={selectedPlan} checkoutMode={checkoutMode} billingPeriod={billingPeriod} status="failed" onBack={() => navigate(routePaths.onboardingPlan)} onPrimary={() => navigate(routePaths.onboardingPlanPayment)} />
    </OnboardingPageShell>
  );
}
