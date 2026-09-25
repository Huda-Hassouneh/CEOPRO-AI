import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { routePaths } from "../../../app/router/routePaths.js";
import { PlanSelector } from "../../billing/components/PlanSelector.jsx";
import { billingApi } from "../../billing/api/billingApi.js";
import { useOnboardingStore } from "../../onboarding/store/onboardingStore.js";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import {
  SectionHeading,
  useLanding
} from "../components/LandingPrimitives.jsx";
import "../../billing/styles/Billing.css";

export function PricingSection() {
  const { t } = useLanding();
  const { locale } = useI18n(); // 1. Added locale to extract Arabic vs English
  const navigate = useNavigate();

  // Fetch plans using SWR
  const {
    data: response,
    error,
    isLoading
  } = useSWR("subscription-plans", billingApi.getPlans);

  const rawPlans = response?.data ?? [];

  // 2. Sort by tier_level and map localized text before rendering[cite: 1]
  const plans = useMemo(() => {
    if (!rawPlans.length) return [];

    return [...rawPlans]
      .sort((a, b) => (a.tier_level || 0) - (b.tier_level || 0))
      .map((plan) => ({
        ...plan,
        displayName: locale === "ar" && plan.name_ar ? plan.name_ar : plan.name,
        displayDescription:
          locale === "ar" && plan.description_ar
            ? plan.description_ar
            : plan.description
      }));
  }, [rawPlans, locale]);

  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const setBillingPeriod = useOnboardingStore(
    (state) => state.setBillingPeriod
  );
  console.log({ plansInSystem: plans });

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

        {isLoading && (
          <p className="lp-centered" style={{ padding: "2rem 0" }}>
            {t("pricing.loading") || "Loading plans..."}
          </p>
        )}

        {error && (
          <p
            className="lp-centered"
            style={{ padding: "2rem 0", color: "var(--color-danger, red)" }}
          >
            {t("pricing.error") ||
              "Failed to load pricing plans. Please try again later."}
          </p>
        )}

        {!isLoading && !error && (
          <PlanSelector
            plans={plans}
            billingPeriod={period}
            onPeriodChange={setPeriod}
            onPlanSelect={choose}
            onBuildCustom={() => choose("custom")}
            showCustomPlan
          />
        )}

        <p className="lp-fineprint lp-centered">
          {t("pricing.note") || "Prices exclude applicable taxes."}
        </p>
      </div>
    </section>
  );
}
