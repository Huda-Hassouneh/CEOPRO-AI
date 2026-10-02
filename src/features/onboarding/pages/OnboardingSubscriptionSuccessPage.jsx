import { useNavigate } from "react-router-dom";
import { routePaths } from "../../../app/router/routePaths.js";
import { SubscriptionResult } from "../../billing/components/SubscriptionResult.jsx";
import { useSubscriptionConfirmation } from "../../billing/hooks/useSubscriptionConfirmation.js";
import { useSubscriptionRecovery } from "../../billing/hooks/useSubscriptionRecovery.js";
import { isRecoverableSubscriptionStatus } from "../../billing/utils/subscriptionStatus.js";
import { OnboardingPageShell } from "../components/OnboardingPageShell.jsx";
import { useOnboardingStore } from "../store/onboardingStore.js";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";


export function OnboardingSubscriptionSuccessPage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  const completePlanStep = useOnboardingStore(
    (state) => state.completePlanStep
  );
  const confirmation = useSubscriptionConfirmation();
  const recovery = useSubscriptionRecovery();

  const continueOnboarding = () => {
    completePlanStep();
    navigate(routePaths.onboardingConnectData);
  };

  const canRecover = Boolean(
    confirmation.subscription &&
      isRecoverableSubscriptionStatus(confirmation.subscription.status)
  );

  return (
    <OnboardingPageShell wide showProgress={false}>
      <SubscriptionResult
        status={confirmation.status}
        checking={confirmation.isChecking}
        onRetry={confirmation.retry}
        onBack={() => navigate(routePaths.onboardingPlan)}
        onPrimary={
          confirmation.status === "confirmed"
            ? continueOnboarding
            : canRecover
              ? recovery.recover
              : undefined
        }
        primaryLoading={recovery.isRecovering}
        primaryLoadingLabel={t("billing.recovery.redirecting")}
        primaryLabel={
          confirmation.status === "confirmed"
            ? t("onboarding.paymentSuccess.continueSetup")
            : undefined
        }
        actionError={recovery.error ? t("billing.recovery.failed") : null}
      />
    </OnboardingPageShell>
  );
}
