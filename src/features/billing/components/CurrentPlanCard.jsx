import { CalendarDays, CreditCard, Crown, AlertTriangle } from "lucide-react";

import Badge from "../../../shared/components/ui/Badge.jsx";

/*
 * ============================================================================
 * PLAN HELPERS
 * ============================================================================
 */

const getPlanName = (plan, locale, t) => {
  if (!plan) return "";

  if (plan.displayName) {
    return plan.displayName;
  }

  if (locale === "ar" && plan.name_ar) {
    return plan.name_ar;
  }

  if (typeof plan.name === "object") {
    return plan.name?.[locale] || (plan.nameKey ? t(plan.nameKey) : plan.id);
  }

  if (plan.name) {
    return plan.name;
  }

  return plan.nameKey ? t(plan.nameKey) : plan.id;
};

const getPlanDescription = (plan, locale) => {
  if (!plan) return null;

  if (plan.displayDescription) {
    return plan.displayDescription;
  }

  if (locale === "ar" && plan.description_ar) {
    return plan.description_ar;
  }

  return plan.description;
};

const getPlanPricing = (plan, billingPeriod) => {
  const option = plan?.pricingOptions?.find(
    (item) => item.period === billingPeriod
  );

  const total =
    option?.totalPrice ??
    option?.price ??
    plan?.basePrice ??
    plan?.monthlyPrice;

  if (total == null) {
    return null;
  }

  return {
    total,
    currency: plan.currency || "USD"
  };
};

const getPlanBillingPeriod = (plan, billingPeriod) => {
  const configured = plan?.pricingOptions?.find(
    (option) => option.period === billingPeriod
  );
  if (configured?.months) return { months: configured.months };

  const known = {
    monthly: 1,
    "three-months": 3,
    "six-months": 6,
    yearly: 12
  };
  return { months: known[billingPeriod] || 1 };
};

const formatCurrency = (amount, currency, locale) =>
  new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(amount || 0);

/*
 * ============================================================================
 * STATUS HELPERS
 * ============================================================================
 */

const normalizeStatus = (status) => {
  if (!status) {
    return "pending";
  }

  /*
   * Support old Stripe spelling and your
   * local database spelling.
   */
  if (status === "canceled") {
    return "cancelled";
  }

  return status;
};

const getStatusVariant = (status) => {
  switch (status) {
    case "active":
      return "light-success";

    case "trialing":
      return "primary";

    case "past_due":
    case "payment_failed":
      return "warning";

    case "paused":
    case "pending":
      return "secondary";

    case "cancelled":
    case "expired":
      return "error";

    default:
      return "secondary";
  }
};

/*
 * ============================================================================
 * COMPONENT
 * ============================================================================
 */

export function CurrentPlanCard({
  subscription,
  plan,
  locale,
  t,
  formatDate,
  currentSubscription
}) {
  /*
   * Use the actual subscription status.
   */
  const status = normalizeStatus(subscription?.status);

  /*
   * IMPORTANT:
   *
   * A scheduled plan change / downgrade is NOT
   * cancellation.
   *
   * scheduledPlanId can exist while:
   *
   * status = active
   *
   * and the badge should remain "Active".
   */
  const hasScheduledPlanChange = Boolean(currentSubscription?.scheduledPlanId);
  const scheduledPlan = currentSubscription?.scheduledPlan ?? null;
  const scheduledPlanName = scheduledPlan
    ? getPlanName(scheduledPlan, locale, t)
    : null;
  const scheduledEffectiveAt = hasScheduledPlanChange
    ? currentSubscription?.currentPeriodEnd ?? subscription?.renewsAt ?? null
    : null;

  /*
   * Cancellation should be based on
   * cancelAtPeriodEnd.
   *
   * Do NOT use scheduledPlanId here.
   */
  const isCancellationScheduled = Boolean(
    currentSubscription?.cancelAtPeriodEnd
  );

  const isActuallyCancelled = status === "cancelled";

  const period = getPlanBillingPeriod(plan, subscription.billingPeriod);

  const pricing = getPlanPricing(plan, subscription.billingPeriod);

  const planName = getPlanName(plan, locale, t);

  const planDescription = getPlanDescription(plan, locale);

  /*
   * ========================================================
   * TRIAL
   * ========================================================
   */

  const trialEnd =
    status === "trialing" && subscription.currentPeriodEnd
      ? new Date(subscription.currentPeriodEnd)
      : null;

  const daysRemaining = trialEnd
    ? Math.max(0, Math.ceil((trialEnd.getTime() - Date.now()) / 86400000))
    : null;

  const statusVariant = getStatusVariant(status);

  /*
   * ========================================================
   * STATUS LABEL
   * ========================================================
   */

  const statusLabel = t(`billing.management.status.${status}`) || status;

  return (
    <section
      className="billing-current-plan"
      aria-labelledby="current-plan-title"
    >
      <div className="billing-current-plan__identity">
        <span className="billing-current-plan__icon">
          <Crown size={24} />
        </span>

        <div>
          <small id="current-plan-title">
            {t("billing.management.currentPlanTitle")}
          </small>

          <h2>
            {status === "trialing"
              ? t("billing.management.planTrial", {
                  plan: planName
                })
              : planName}
          </h2>

          {planDescription && (
            <p
              style={{
                fontSize: "13px",
                color: "var(--ceopro-text-muted)",
                margin: "4px 0 8px 0"
              }}
            >
              {planDescription}
            </p>
          )}

          {/*
           * ==================================================
           * STATUS
           * ==================================================
           *
           * Example:
           *
           * [ Active ]   ● Cancels Soon
           *
           * The actual status remains Active.
           */}

          <div
            style={{
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "8px"
            }}
          >
            <Badge variant={statusVariant}>{statusLabel}</Badge>

            {/*
             * Cancellation indicator.
             *
             * This is deliberately separate from
             * the status Badge.
             */}
            {isCancellationScheduled && !isActuallyCancelled && (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "var(--ceopro-error, #dc2626)",
                  whiteSpace: "nowrap"
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    position: "relative",
                    display: "inline-flex",
                    width: "8px",
                    height: "8px"
                  }}
                >
                  <span
                    style={{
                      position: "absolute",
                      inset: 0,
                      borderRadius: "9999px",
                      backgroundColor: "var(--ceopro-error, #dc2626)",
                      opacity: 0.25,
                      transform: "scale(1.7)"
                    }}
                  />

                  <span
                    style={{
                      position: "relative",
                      display: "inline-block",
                      width: "8px",
                      height: "8px",
                      borderRadius: "9999px",
                      backgroundColor: "var(--ceopro-error, #dc2626)"
                    }}
                  />
                </span>
              </span>
            )}
          </div>
        </div>
      </div>

      {/*
       * ======================================================
       * CANCELLATION WARNING
       * ======================================================
       */}

      {isCancellationScheduled && !isActuallyCancelled && (
        <div
          className="billing-current-plan__warning"
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "12px 16px",
            marginTop: "16px",
            backgroundColor: "var(--ceopro-error-light, #fef2f2)",
            border: "1px solid var(--ceopro-error-border, #fecaca)",
            color: "var(--ceopro-error, #dc2626)",
            borderRadius: "8px",
            fontSize: "13px",
            lineHeight: "1.4"
          }}
        >
          <AlertTriangle
            size={16}
            style={{
              flexShrink: 0,
              marginTop: "2px"
            }}
          />

          <span>
            {t("billing.management.cancellationWarning") ||
              "Your subscription is scheduled to be canceled. You will keep access until the end of the current billing period."}
          </span>
        </div>
      )}

      {hasScheduledPlanChange && scheduledPlan && !isActuallyCancelled && (
        <div
          className="billing-current-plan__warning"
          style={{
            display: "grid",
            gap: "10px",
            padding: "14px 16px",
            marginTop: "16px",
            backgroundColor: "var(--ceopro-surface-soft)",
            border: "1px solid var(--ceopro-border)",
            color: "var(--ceopro-text-primary)",
            borderRadius: "8px",
            fontSize: "13px",
            lineHeight: "1.5"
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "12px",
              flexWrap: "wrap"
            }}
          >
            <strong>{t("billing.management.scheduledChangeTitle")}</strong>
            <Badge variant="warning">
              {t("billing.management.scheduled")}
            </Badge>
          </div>

          <div>
            <strong>{t("billing.management.nextPlan")}:</strong>{" "}
            {scheduledPlanName}
          </div>

          {scheduledEffectiveAt && (
            <div>
              <strong>{t("billing.management.effectiveDate")}:</strong>{" "}
              {formatDate(scheduledEffectiveAt)}
            </div>
          )}

          <span style={{ color: "var(--ceopro-text-secondary)" }}>
            {t("billing.management.scheduledChangeExplanation", {
              currentPlan: planName,
              nextPlan: scheduledPlanName,
              date: scheduledEffectiveAt
                ? formatDate(scheduledEffectiveAt)
                : t("billing.management.endOfCurrentCycle")
            })}
          </span>
        </div>
      )}

      {/*
       * ======================================================
       * SUBSCRIPTION DETAILS
       * ======================================================
       */}

      <dl
        style={{
          marginTop: isCancellationScheduled ? "16px" : undefined
        }}
      >
        <div>
          <dt>
            <CreditCard size={14} />

            {t("billing.management.billingCycle")}
          </dt>

          <dd>
            {period.months === 1
              ? t("billing.periods.monthly")
              : t("billing.periods.monthCountLabel", {
                  months: period.months
                })}
          </dd>
        </div>

        {pricing && (
          <div>
            <dt>{t("billing.management.planPrice")}</dt>

            <dd>{formatCurrency(pricing.total, pricing.currency, locale)}</dd>
          </div>
        )}

        {subscription.renewsAt && (
          <div>
            <dt>
              <CalendarDays size={14} />

              {isCancellationScheduled
                ? t("billing.management.cancelsOn") || "Active Until"
                : t("billing.management.nextBillingDate")}
            </dt>

            <dd>{formatDate(subscription.renewsAt)}</dd>
          </div>
        )}

        {trialEnd && (
          <div>
            <dt>
              <CalendarDays size={14} />

              {t("billing.management.trialEndDate")}
            </dt>

            <dd>
              {formatDate(trialEnd)}

              {daysRemaining != null && (
                <small>
                  {t("billing.management.daysRemaining", {
                    count: daysRemaining
                  })}
                </small>
              )}
            </dd>
          </div>
        )}
      </dl>

      {/*
       * This value is intentionally computed independently
       * from cancellation.
       *
       * A future downgrade/upgrade does NOT make the
       * subscription inactive.
       */}
      {hasScheduledPlanChange && status === "active" && (
        <span
          style={{
            display: "none"
          }}
          aria-hidden="true"
        />
      )}
    </section>
  );
}
