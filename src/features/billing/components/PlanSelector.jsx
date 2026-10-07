import { AlertCircle, Zap } from "lucide-react";
import SegmentedControl from "../../../shared/components/ui/SegmentedControl.jsx";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { CustomPlanCallout } from "./CustomPlanCallout.jsx";
import { PlanCard } from "./PlanCard.jsx";
import {
  describeBillingOption,
  listBillingPeriods
} from "../utils/billingPeriodPresentation.js";

const getSupportedPeriods = (plans) =>
  listBillingPeriods(plans).map((period) => ({ ...period, value: period.period }));

const normalizePlanName = (plan) => String(plan?.name || "").trim().toLowerCase();
const isFeaturedPlan = (plan) =>
  plan?.featured === true || normalizePlanName(plan) === "growth";

export function PlanSelector({
  plans = [],
  selectedPlan,
  billingPeriod = "monthly",
  onPlanSelect,
  onPeriodChange,
  onBuildCustom,
  showCustomPlan = true
}) {
  const { t } = useI18n();
  const activePlans = [...plans]
    .filter((plan) => plan?.isActive !== false)
    .sort((a, b) => (a.tier_level || a.tierLevel || 0) - (b.tier_level || b.tierLevel || 0));

  if (!activePlans.length && !showCustomPlan) {
    return (
      <div
        className="ceopro-empty-state"
        style={{ textAlign: "center", padding: "2rem" }}
      >
        <AlertCircle size={32} style={{ margin: "0 auto", opacity: 0.5 }} />
        <h3>{t("billing.emptyState.title") || "No Plans Available"}</h3>
        <p>
          {t("billing.emptyState.description") ||
            "There are currently no subscription plans available to select."}
        </p>
      </div>
    );
  }

  const periods = getSupportedPeriods(activePlans);
  const periodOptions = periods.map((period) => ({
    value: period.value,
    label: period.mixedIntervals
      ? period.period
      : describeBillingOption(period, t),
    badge:
      period.discountPercent > 0 && !period.mixedDiscounts
        ? t("billing.periods.savePercent", { percent: period.discountPercent })
        : undefined
  }));
  const hasTrialPlans = activePlans.some(
    (plan) => Number(plan?.trialPeriodValue) > 0
  );

  return (
    <div>
      {hasTrialPlans && (
        <div className="ceopro-trial-banner">
          <Zap size={20} fill="currentColor" aria-hidden="true" />
          <span>
            <strong>{t("billing.trial.title")}</strong>
            <small>{t("billing.trial.description")}</small>
          </span>
          <b>{t("billing.trial.badge")}</b>
        </div>
      )}

      {periodOptions.length > 0 && (
        <div className="ceopro-billing-period-row">
          <SegmentedControl
            name="billing-period"
            value={billingPeriod}
            options={periodOptions}
            onChange={onPeriodChange}
            ariaLabel={t("billing.periods.label")}
          />
        </div>
      )}

      <div className="ceopro-plan-grid">
        {activePlans.map((plan, index) => (
          <PlanCard
            key={plan.id}
            plan={isFeaturedPlan(plan) ? { ...plan, featured: true } : plan}
            previousPlan={index > 0 ? activePlans[index - 1] : null}
            compactSummary
            billingPeriod={billingPeriod}
            selected={selectedPlan === plan.id}
            onSelect={() => onPlanSelect?.(plan.id)}
          />
        ))}
      </div>

      {showCustomPlan && (
        <CustomPlanCallout
          actionLabel={t("billing.plans.custom.action") || "Build Your Plan"}
          onSelect={() =>
            onBuildCustom ? onBuildCustom() : onPlanSelect?.("custom")
          }
        />
      )}
    </div>
  );
}
