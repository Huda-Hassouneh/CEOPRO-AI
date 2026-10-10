import { useEffect, useState, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { routePaths } from "../../../app/router/routePaths.js";
import { PlanSelector } from "../../billing/components/PlanSelector.jsx";
import { billingApi } from "../../billing/api/billingApi.js";
import { useOnboardingStore } from "../../onboarding/store/onboardingStore.js";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { SlidersHorizontal } from "lucide-react";
import Button from "../../../shared/components/ui/Button.jsx";
import {
  SectionHeading,
  useLanding
} from "../components/LandingPrimitives.jsx";
import "../../billing/styles/Billing.css";

function LandingCustomPlan({ onSelect }) {
  const { t } = useLanding();
  return (
    <aside className="ceopro-custom-plan-callout lp-custom-plan-details">
      <span className="ceopro-custom-plan-callout__icon" aria-hidden="true">
        <SlidersHorizontal size={22} />
      </span>
      <div className="ceopro-custom-plan-callout__copy">
        <small>{t("pricing.customPrice")}</small>
        <h3>{t("pricing.customTitle")}</h3>
        <p>{t("pricing.customDescription")}</p>
        <p>{t("pricing.customPriceNote")}</p>
      </div>
      <div className="ceopro-custom-plan-callout__copy lp-custom-plan-criteria">
        <p>{t("pricing.customHow")}</p>
        <ul>
          {["customBusiness", "customUsage", "customTeam", "customData"].map((key) => (
            <li key={key}><p>{t(`pricing.${key}`)}</p></li>
          ))}
        </ul>
      </div>
      <Button variant="outline" onClick={onSelect}>{t("common.customPlan")}</Button>
    </aside>
  );
}

export function PricingSection() {
  const { t } = useLanding();
  const { locale } = useI18n();
  const navigate = useNavigate();
  const {
    data: response,
    error,
    isLoading,
    mutate
  } = useSWR("subscription-plans", billingApi.getPlans, { shouldRetryOnError: false });

  const retryLock = useRef(false);
  const [retrying, setRetrying] = useState(false);
  const retry = async () => {
    if (retryLock.current) return;
    retryLock.current = true;
    setRetrying(true);
    try { await mutate(); } catch { /* SWR retains the catalog error for display. */ }
    finally { retryLock.current = false; setRetrying(false); }
  };

  const rawPlans = response?.data ?? [];

  const plans = useMemo(() => {
    if (!rawPlans.length) return [];
    const arabicPlanNames = {
      starter: t("pricing.planNames.starter"),
      growth: t("pricing.planNames.growth"),
      enterprise: t("pricing.planNames.enterprise")
    };

    return [...rawPlans]
      .filter((plan) => plan.isActive !== false)
      .sort((a, b) => (a.tier_level || 0) - (b.tier_level || 0))
      .map((plan) => ({
        ...plan,
        displayName: locale === "ar"
          ? plan.name_ar || arabicPlanNames[String(plan.name).trim().toLowerCase()] || plan.name
          : plan.name,
        displayDescription:
          locale === "ar" ? plan.description_ar || "" : plan.description
      }));
  }, [rawPlans, locale]);

  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const setBillingPeriod = useOnboardingStore(
    (state) => state.setBillingPeriod
  );
  const [period, setPeriod] = useState("monthly");

  useEffect(() => {
    const firstPeriod = plans[0]?.pricingOptions?.[0]?.period;
    if (firstPeriod) {
      setPeriod((current) =>
        plans[0].pricingOptions.some((option) => option.period === current)
          ? current
          : firstPeriod
      );
    }
  }, [plans]);

  const choose = (planId) => {
    if (planId === "custom") {
      setPlanChoice("custom", "paid");
      setBillingPeriod(period);
      navigate(routePaths.welcome);
      return;
    }

    const selectedPlan = plans.find((p) => p.id === planId);

    if (selectedPlan) {
      const hasTrial =
        selectedPlan.trialPeriodValue && selectedPlan.trialPeriodValue > 0;

      setPlanChoice(selectedPlan.id, hasTrial ? "trial" : "paid");
      setBillingPeriod(period);
      navigate(routePaths.welcome);
    }
  };

  return (
    <section className="lp-section lp-tinted" id="pricing">
      <div className="lp-container">
        <SectionHeading section="pricing" centered />

        {isLoading || retrying || error || !plans.length ? (
          <div className="lp-pricing-unavailable">
            {isLoading || retrying ? (
              <div className="lp-pricing-state" role="status" aria-live="polite"><span className="lp-loading-dot" />{t("pricing.loading")}</div>
            ) : error ? (
              <div className="lp-pricing-state lp-pricing-state--error" role="alert">
                <h3>{t("pricing.errorTitle")}</h3><p>{t("pricing.error")}</p>
                <Button variant="outline" onClick={retry} disabled={retrying}>{t("pricing.retry")}</Button>
              </div>
            ) : (
              <div className="lp-pricing-state" role="status"><h3>{t("pricing.emptyTitle")}</h3><p>{t("pricing.empty")}</p></div>
            )}
          </div>
        ) : (
          <PlanSelector
            plans={plans}
            billingPeriod={period}
            onPeriodChange={setPeriod}
            onPlanSelect={choose}
            onBuildCustom={() => choose("custom")}
            showCustomPlan={false}
          />
        )}

        <LandingCustomPlan onSelect={() => choose("custom")} />

        <p className="lp-fineprint lp-centered">
          {t("pricing.note") || "Prices exclude applicable taxes."}
        </p>
      </div>
    </section>
  );
}
