import { AlertTriangle, Clock3, PauseCircle } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import { getSubscriptionRecoveryCopyKey } from "../utils/subscriptionStatus.js";

export function SubscriptionRecoveryBanner({
  status,
  onRecover,
  recovering = false,
  error = null
}) {
  const { t } = useI18n();
  const copyKey = getSubscriptionRecoveryCopyKey(status);

  if (!copyKey) {
    return null;
  }

  const Icon =
    copyKey === "pending"
      ? Clock3
      : copyKey === "paused"
        ? PauseCircle
        : AlertTriangle;

  return (
    <section
      className={`billing-recovery-banner billing-recovery-banner--${copyKey}`}
      aria-live="polite"
    >
      <span className="billing-recovery-banner__icon" aria-hidden="true">
        <Icon size={21} />
      </span>

      <div className="billing-recovery-banner__copy">
        <h2>{t(`billing.recovery.${copyKey}.title`)}</h2>
        <p>{t(`billing.recovery.${copyKey}.description`)}</p>
        {error && (
          <p className="billing-recovery-banner__error" role="alert">
            {t("billing.recovery.failed")}
          </p>
        )}
      </div>

      <Button
        onClick={onRecover}
        loading={recovering}
        loadingLabel={t("billing.recovery.redirecting")}
      >
        {t(`billing.recovery.${copyKey}.action`)}
      </Button>
    </section>
  );
}
