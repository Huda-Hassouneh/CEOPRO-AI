import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';
import { SubscriptionResult } from '../components/SubscriptionResult.jsx';
import { useSubscriptionConfirmation } from '../hooks/useSubscriptionConfirmation.js';
import '../styles/Billing.css';

export function PaymentSuccessPage() {
  const navigate = useNavigate();
  const confirmation = useSubscriptionConfirmation();
  const selectedOnboardingPlan = useOnboardingStore((state) => state.selectedPlan);
  const step5Completed = useOnboardingStore((state) => state.step5Completed);
  const completePlanStep = useOnboardingStore((state) => state.completePlanStep);
  const returningToOnboarding = Boolean(selectedOnboardingPlan && !step5Completed);

  const continueAfterConfirmation = () => {
    if (returningToOnboarding) {
      completePlanStep();
      navigate(routePaths.onboardingConnectData);
      return;
    }
    navigate(routePaths.billing);
  };

  return (
    <SubscriptionResult
      status={confirmation.status}
      checking={confirmation.isChecking}
      onRetry={confirmation.retry}
      onBack={() => navigate(returningToOnboarding ? routePaths.onboardingPlan : routePaths.billingPlans)}
      onPrimary={confirmation.status === 'confirmed' ? continueAfterConfirmation : undefined}
    />
  );
}
