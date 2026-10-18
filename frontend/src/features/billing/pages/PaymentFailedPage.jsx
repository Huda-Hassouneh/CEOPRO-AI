import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { useOnboardingStore } from "../../onboarding/store/onboardingStore.js";
import { billingApi, getApiError } from "../api/billingApi.js";
import { SubscriptionResult } from "../components/SubscriptionResult.jsx";
import { useSubscriptionRecovery } from "../hooks/useSubscriptionRecovery.js";
import {
  getSubscriptionResultStatus,
  isRecoverableSubscriptionStatus
} from "../utils/subscriptionStatus.js";
import "../styles/Billing.css";

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

export function PaymentFailedPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const selectedOnboardingPlan = useOnboardingStore(
    (state) => state.selectedPlan
  );
  const step5Completed = useOnboardingStore((state) => state.step5Completed);
  const completePlanStep = useOnboardingStore((state) => state.completePlanStep);
  const returningToOnboarding = Boolean(
    selectedOnboardingPlan && !step5Completed
  );
  const recovery = useSubscriptionRecovery();

  const {
    data: subscriptionResponse,
    error: subscriptionError,
    isLoading,
    isValidating,
    mutate
  } = useSWR(
    "subscription-current-payment-failed",
    () => billingApi.getSubscription(),
    swrOptions
  );

  const apiError = subscriptionError ? getApiError(subscriptionError) : null;
  const subscriptionMissing =
    apiError?.status === 404 || apiError?.code === "SUBSCRIPTION_NOT_FOUND";
  const subscription = subscriptionResponse?.data ?? null;

  const status = isLoading
    ? "checking"
    : subscription
      ? getSubscriptionResultStatus(subscription.status)
      : subscriptionError && !subscriptionMissing
        ? "error"
        : "failed";

  const canRecover = Boolean(
    subscription && isRecoverableSubscriptionStatus(subscription.status)
  );

  const continueAfterConfirmation = () => {
    if (returningToOnboarding) {
      completePlanStep();
      navigate(routePaths.onboardingConnectData);
      return;
    }

    navigate(routePaths.billing);
  };

  const retryCheckout = () =>
    navigate(
      returningToOnboarding
        ? routePaths.onboardingPlanPayment
        : routePaths.billingPlans
    );

  return (
    <SubscriptionResult
      status={status}
      checking={isLoading || isValidating}
      onRetry={() => mutate()}
      onBack={() =>
        navigate(
          returningToOnboarding ? routePaths.onboardingPlan : routePaths.billing
        )
      }
      onPrimary={
        status === "confirmed"
          ? continueAfterConfirmation
          : canRecover
            ? recovery.recover
            : status === "failed"
              ? retryCheckout
              : undefined
      }
      primaryLoading={recovery.isRecovering}
      primaryLoadingLabel={t("billing.recovery.redirecting")}
      primaryLabel={
        status === "confirmed" && returningToOnboarding
          ? t("onboarding.paymentSuccess.continueSetup")
          : undefined
      }
      actionError={recovery.error ? t("billing.recovery.failed") : null}
    />
  );
}
