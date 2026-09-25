import { AlertCircle, Zap } from "lucide-react";
import SegmentedControl from "../../../shared/components/ui/SegmentedControl.jsx";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { PlanCard } from "./PlanCard.jsx";

const getSupportedPeriods = (plans) => {
  const periods = new Map();
  for (const plan of plans) {
    for (const option of plan?.pricingOptions ?? []) {
      if (!option?.period || periods.has(option.period)) continue;
      periods.set(option.period, {
        value: option.period,
        months: option.months ?? 1,
        discountPercent: option.discountPercent ?? 0
      });
    }
  }
  return Array.from(periods.values()).sort((a, b) => a.months - b.months);
};

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
  const activePlans = plans.filter((plan) => plan?.isActive !== false);

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
    label:
      period.months === 1
        ? t("billing.periods.monthly")
        : t("billing.periods.monthCountLabel", { months: period.months }),
    badge:
      period.discountPercent > 0
        ? t("billing.periods.savePercent", { percent: period.discountPercent })
        : undefined
  }));
  const trialPlan = activePlans.find(
    (plan) => Number(plan?.trialPeriodValue) > 0
  );
  const customPlan = {
    id: "custom",
    name: t("billing.plans.custom.name") || "Custom",
    description:
      t("billing.plans.custom.description") || "Tailored for your business",
    displayName: t("billing.plans.custom.name") || "Custom",
    displayDescription:
      t("billing.plans.custom.description") ||
      "Choose your own features and quotas",
    isCustomBuilder: true,
    isActive: true,
    features: {},
    pricingOptions: []
  };

  return (
    <div>
      {trialPlan && (
        <div className="ceopro-trial-banner">
          <Zap size={20} fill="currentColor" aria-hidden="true" />
          <span>
            <strong>
              {t("billing.trial.title", { days: trialPlan.trialPeriodValue })}
            </strong>
            <small>{t("billing.trial.description")}</small>
          </span>
          <b>
            {t("billing.trial.badge", { days: trialPlan.trialPeriodValue })}
          </b>
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
            plan={index === 1 ? { ...plan, featured: true } : plan}
            billingPeriod={billingPeriod}
            selected={selectedPlan === plan.id}
            onSelect={() => onPlanSelect?.(plan.id)}
          />
        ))}
        {showCustomPlan && (
          <PlanCard
            key="custom"
            plan={customPlan}
            billingPeriod={billingPeriod}
            selected={selectedPlan === "custom"}
            actionLabel={t("billing.plans.custom.action") || "Build Your Plan"}
            onSelect={() =>
              onBuildCustom ? onBuildCustom() : onPlanSelect?.("custom")
            }
          />
        )}
      </div>
    </div>
  );
}
