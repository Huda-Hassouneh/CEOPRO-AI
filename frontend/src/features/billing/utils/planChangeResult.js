const PLAN_CHANGE_STATES = new Set([
  "applied",
  "payment_action_required",
  "payment_pending",
  "scheduled",
  "failed"
]);

export const normalizePlanChangeState = (state) =>
  typeof state === "string" ? state.trim().toLowerCase() : "";

export const isKnownPlanChangeState = (state) =>
  PLAN_CHANGE_STATES.has(normalizePlanChangeState(state));

export const isPlanChangePaymentRecoveryState = (state) => {
  const normalized = normalizePlanChangeState(state);
  return (
    normalized === "payment_action_required" ||
    normalized === "payment_pending" ||
    normalized === "failed"
  );
};

export const getPlanChangeNotice = (result, t, { trialing = false } = {}) => {
  const state = normalizePlanChangeState(result?.state);

  if (state === "applied") {
    return {
      variant: "success",
      message: trialing
        ? t("billing.checkoutInApp.planChangeStates.trialApplied")
        : t("billing.checkoutInApp.planChangeStates.applied")
    };
  }

  if (state === "scheduled") {
    return {
      variant: "info",
      message: t("billing.checkoutInApp.planChangeStates.scheduled")
    };
  }

  if (state === "payment_action_required") {
    return {
      variant: "warning",
      message: t("billing.checkoutInApp.planChangeStates.paymentActionRequired")
    };
  }

  if (state === "payment_pending") {
    return {
      variant: "info",
      message: t("billing.checkoutInApp.planChangeStates.paymentPending")
    };
  }

  if (state === "failed") {
    return {
      variant: "error",
      message: t("billing.checkoutInApp.planChangeStates.failed")
    };
  }

  return {
    variant: "error",
    message: t("billing.checkoutInApp.planChangeStates.unknown")
  };
};

export const getPlanChangeRecoveryLabel = (state, t) => {
  const normalized = normalizePlanChangeState(state);

  if (normalized === "payment_action_required") {
    return t("billing.checkoutInApp.planChangeStates.completePayment");
  }

  if (normalized === "payment_pending") {
    return t("billing.checkoutInApp.planChangeStates.reviewPayment");
  }

  if (normalized === "failed") {
    return t("billing.checkoutInApp.planChangeStates.resolvePayment");
  }

  return null;
};
