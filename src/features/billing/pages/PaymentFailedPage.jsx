import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';
import { SubscriptionResult } from '../components/SubscriptionResult.jsx';
import '../styles/Billing.css';

export function PaymentFailedPage() {
  const navigate = useNavigate();
  const selectedOnboardingPlan = useOnboardingStore((state) => state.selectedPlan);
  const step5Completed = useOnboardingStore((state) => state.step5Completed);
  const returningToOnboarding = Boolean(selectedOnboardingPlan && !step5Completed);

  return (
    <SubscriptionResult
      status="failed"
      onBack={() => navigate(returningToOnboarding ? routePaths.onboardingPlan : routePaths.billing)}
      onPrimary={() => navigate(returningToOnboarding ? routePaths.onboardingPlanPayment : routePaths.billingPlans)}
    />
  );
}
