import { useNavigate } from "react-router-dom";
import { routePaths } from "../../../app/router/routePaths.js";
import { SubscriptionResult } from "../../billing/components/SubscriptionResult.jsx";
import { useSubscriptionConfirmation } from "../../billing/hooks/useSubscriptionConfirmation.js";
import { OnboardingPageShell } from "../components/OnboardingPageShell.jsx";
import { useOnboardingStore } from "../store/onboardingStore.js";

export function OnboardingSubscriptionSuccessPage() {
  const navigate = useNavigate();
  const completePlanStep = useOnboardingStore(
    (state) => state.completePlanStep
  );
  const confirmation = useSubscriptionConfirmation();

  const continueOnboarding = () => {
    completePlanStep();
    navigate(routePaths.onboardingConnectData);
  };

  return (
    <OnboardingPageShell wide showProgress={false}>
      <SubscriptionResult
        status={confirmation.status}
        checking={confirmation.isChecking}
        onRetry={confirmation.retry}
        onBack={() => navigate(routePaths.onboardingPlan)}
        onPrimary={
          confirmation.status === "confirmed" ? continueOnboarding : undefined
        }
      />
    </OnboardingPageShell>
  );
}
