import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { useOnboardingStore } from "../../onboarding/store/onboardingStore.js";
import { SubscriptionResult } from "../components/SubscriptionResult.jsx";
import { useSubscriptionConfirmation } from "../hooks/useSubscriptionConfirmation.js";
import { useSubscriptionRecovery } from "../hooks/useSubscriptionRecovery.js";
import { isRecoverableSubscriptionStatus } from "../utils/subscriptionStatus.js";
import "../styles/Billing.css";


export function PaymentSuccessPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const confirmation = useSubscriptionConfirmation();
  const recovery = useSubscriptionRecovery();
  const selectedOnboardingPlan = useOnboardingStore(
    (state) => state.selectedPlan
  );
  const step5Completed = useOnboardingStore((state) => state.step5Completed);
  const completePlanStep = useOnboardingStore((state) => state.completePlanStep);
  const returningToOnboarding = Boolean(
    selectedOnboardingPlan && !step5Completed
  );

  const continueAfterConfirmation = () => {
    if (returningToOnboarding) {
      completePlanStep();
      navigate(routePaths.onboardingConnectData);
      return;
    }
    navigate(routePaths.billing);
  };

  const canRecover = Boolean(
    confirmation.subscription &&
      isRecoverableSubscriptionStatus(confirmation.subscription.status)
  );

  return (
    <SubscriptionResult
      status={confirmation.status}
      checking={confirmation.isChecking}
      onRetry={confirmation.retry}
      onBack={() =>
        navigate(
          returningToOnboarding
            ? routePaths.onboardingPlan
            : routePaths.billingPlans
        )
      }
      onPrimary={
        confirmation.status === "confirmed"
          ? continueAfterConfirmation
          : canRecover
            ? recovery.recover
            : undefined
      }
      primaryLoading={recovery.isRecovering}
      primaryLoadingLabel={t("billing.recovery.redirecting")}
      actionError={recovery.error ? t("billing.recovery.failed") : null}
    />
  );
}
