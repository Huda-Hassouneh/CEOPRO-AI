import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { SubscriptionResult } from '../../billing/components/SubscriptionResult.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';

export function OnboardingSubscriptionFailedPage() {
  const navigate = useNavigate();
  return (
    <OnboardingPageShell wide showProgress={false}>
      <SubscriptionResult
        status="failed"
        onBack={() => navigate(routePaths.onboardingPlan)}
        onPrimary={() => navigate(routePaths.onboardingPlanPayment)}
      />
    </OnboardingPageShell>
  );
}
