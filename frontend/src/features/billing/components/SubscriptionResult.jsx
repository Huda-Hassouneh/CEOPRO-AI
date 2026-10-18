import { AlertTriangle, Check, Clock3, PauseCircle, X } from "lucide-react";

import Button from "../../../shared/components/ui/Button.jsx";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";

export function SubscriptionResult({
  status,
  onPrimary,
  onBack,
  onRetry,
  checking = false,
  primaryLoading = false,
  primaryLoadingLabel,
  primaryLabel,
  actionError = null
}) {
  const { t } = useI18n();

  const success = status === "confirmed";
  const pending = status === "pending" || status === "checking";
  const paymentIssue = status === "payment_issue";
  const paused = status === "paused";
  const error = status === "error";

  const Icon = success
    ? Check
    : pending
      ? Clock3
      : paymentIssue
        ? AlertTriangle
        : paused
          ? PauseCircle
          : X;

  const copyKey = success
    ? "confirmed"
    : pending
      ? "pending"
      : paymentIssue
        ? "paymentIssue"
        : paused
          ? "paused"
          : error
            ? "error"
            : "failed";

  const stateClass = success
    ? "is-success"
    : pending
      ? "is-pending"
      : paymentIssue || paused
        ? "is-warning"
        : "is-failed";

  // Existing subscriptions with a recoverable billing problem should not be
  // pushed back through fresh plan checkout. Terminal states can return there.
  const showBackToPlans =
    onBack && !success && !pending && !paymentIssue && !paused;

  // Rechecking is useful while Stripe/webhook state can still change, or after
  // a transient backend error. Payment issues can also be resolved elsewhere.
  const showRetry = onRetry && (pending || error || paymentIssue);

  return (
    <section className={`ceopro-subscription-result ${stateClass}`}>
      <span className="ceopro-subscription-result__icon" aria-hidden="true">
        <Icon size={40} />
      </span>

      <h1>{t(`billing.result.${copyKey}.title`)}</h1>

      <p>{t(`billing.result.${copyKey}.description`)}</p>

      {actionError && (
        <p className="ceopro-subscription-result__action-error" role="alert">
          {actionError}
        </p>
      )}

      <div className="ceopro-subscription-result__actions">
        {showBackToPlans && (
          <Button variant="outline" onClick={onBack} disabled={primaryLoading}>
            {t("billing.result.backToPlans")}
          </Button>
        )}

        {showRetry && (
          <Button
            variant="outline"
            onClick={onRetry}
            loading={checking}
            loadingLabel={t("billing.result.checking")}
            disabled={primaryLoading}
          >
            {t("billing.result.checkAgain")}
          </Button>
        )}

        {onPrimary && (
          <Button
            onClick={onPrimary}
            loading={primaryLoading}
            loadingLabel={
              primaryLoadingLabel ?? t("billing.recovery.redirecting")
            }
            disabled={pending && checking}
          >
            {primaryLabel ??
              (success
                ? t("billing.result.goToBilling")
                : t(`billing.result.${copyKey}.action`))}
          </Button>
        )}
      </div>
    </section>
  );
}
