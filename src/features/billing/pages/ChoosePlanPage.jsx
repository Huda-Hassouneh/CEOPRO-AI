import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import useSWR from "swr";

import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import {
  selectIsAuthenticated,
  useAuthStore
} from "../../auth/store/authStore.js";
import { routePaths } from "../../../app/router/routePaths.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import SegmentedControl from "../../../shared/components/ui/SegmentedControl.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { billingApi, getApiError } from "../api/billingApi.js";
import { PlanCard } from "../components/PlanCard.jsx";
import { PlanComparisonTable } from "../components/PlanComparisonTable.jsx";

import "../styles/Billing.css";
import "../styles/PlansSubscription.css";

const getPlanPricingOptions = (plan = {}) => plan.pricingOptions || [];
const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

export function ChoosePlanPage() {
  const { t, dir, locale } = useI18n();
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const [notice, setNotice] = useState(null);
  const [billingPeriod, setBillingPeriod] = useState("monthly");

  const {
    data: plansResponse,
    isLoading: plansLoading,
    error: plansError
  } = useSWR("subscription-plans", billingApi.getPlans, swrOptions);
  const {
    data: coreSubResponse,
    isLoading: coreSubLoading,
    error: coreSubError
  } = useSWR(
    isAuthenticated ? "subscription-current" : null,
    billingApi.getSubscription,
    swrOptions
  );

  const rawPlans = plansResponse?.data ?? [];
  const plans = useMemo(
    () =>
      [...rawPlans]
        .sort((a, b) => (a.tier_level || 0) - (b.tier_level || 0))
        .map((plan) => ({
          ...plan,
          displayName:
            locale === "ar" && plan.name_ar ? plan.name_ar : plan.name,
          displayDescription:
            locale === "ar" && plan.description_ar
              ? plan.description_ar
              : plan.description
        })),
    [rawPlans, locale]
  );

  const subscriptionError = coreSubError ? getApiError(coreSubError) : null;
  const subscriptionMissing =
    subscriptionError?.code === "SUBSCRIPTION_NOT_FOUND" ||
    subscriptionError?.status === 404;
  const subscription = coreSubResponse?.data ?? null;
  const currentPlan = subscription
    ? plans.find((plan) => plan.id === subscription.planId)
    : null;

  const dynamicPeriods = useMemo(() => {
    const map = new Map();
    plans.forEach((plan) => {
      getPlanPricingOptions(plan).forEach((option) => {
        if (!option?.period || map.has(option.period)) return;
        map.set(option.period, {
          value: option.period,
          months: option.months ?? 1,
          discountPercent: option.discountPercent ?? 0
        });
      });
    });
    return Array.from(map.values()).sort((a, b) => a.months - b.months);
  }, [plans]);

  useEffect(() => {
    if (
      dynamicPeriods.length &&
      !dynamicPeriods.some((period) => period.value === billingPeriod)
    ) {
      setBillingPeriod(dynamicPeriods[0].value);
    }
  }, [billingPeriod, dynamicPeriods]);

  useEffect(() => {
    if (
      subscription?.billingPeriod &&
      dynamicPeriods.some(
        (period) => period.value === subscription.billingPeriod
      )
    ) {
      setBillingPeriod(subscription.billingPeriod);
    }
  }, [dynamicPeriods, subscription?.billingPeriod]);

  const periodOptions = useMemo(
    () =>
      dynamicPeriods.map((period) => ({
        value: period.value,
        label:
          period.months === 1
            ? t("billing.periods.monthly")
            : t("billing.periods.monthCountLabel", { months: period.months }),
        badge:
          period.discountPercent > 0
            ? t("billing.periods.savePercent", {
                percent: period.discountPercent
              })
            : undefined
      })),
    [dynamicPeriods, t]
  );

  const selectablePlans = useMemo(
    () =>
      plans.filter((plan) =>
        getPlanPricingOptions(plan).some(
          (option) => option.period === billingPeriod
        )
      ),
    [billingPeriod, plans]
  );

  const customPlan = useMemo(
    () => ({
      id: "custom",
      name: t("billing.plans.custom.name") || "Custom",
      description:
        t("billing.plans.custom.description") ||
        "Choose the features and quotas that fit your business.",
      displayName: t("billing.plans.custom.name") || "Custom",
      displayDescription:
        t("billing.plans.custom.description") ||
        "Choose the features and quotas that fit your business.",
      isCustomBuilder: true,
      isActive: true,
      features: {},
      pricingOptions: []
    }),
    [t]
  );

  const handlePlanSelection = (plan) => {
    navigate(
      `${routePaths.billingCheckout}?plan=${encodeURIComponent(plan.id)}&period=${encodeURIComponent(billingPeriod)}`
    );
  };

  if (plansLoading || (isAuthenticated && coreSubLoading)) {
    return (
      <div className="billing-checkout-loading">
        <Skeleton height="360px" variant="rectangular" />
      </div>
    );
  }

  if (plansError || (coreSubError && !subscriptionMissing)) {
    const error = getApiError(plansError || coreSubError);
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.management.compareTitle")}
          subtitle={t("billing.management.compareSubtitle")}
        />
        <p className="billing-inline-error">{error.message}</p>
      </div>
    );
  }

  return (
    <div className="billing-management-page" dir={dir}>
      <Link className="billing-back-link" to={routePaths.billing}>
        <ArrowLeft className="ceopro-setup-direction-icon" size={15} />
        {t("billing.checkoutInApp.backToBilling")}
      </Link>

      <PageHeader
        title={t("billing.management.compareTitle")}
        subtitle={t("billing.management.compareSubtitle")}
      />

      <div className="tab-content-fade-in">
        <section className="billing-management-section billing-compare-section">
          <header className="billing-compare-header">
            <SegmentedControl
              name="in-app-billing-period"
              value={billingPeriod}
              onChange={setBillingPeriod}
              options={periodOptions}
            />
          </header>

          <div className="ceopro-plan-grid billing-management-plans">
            {selectablePlans.map((plan) => {
              const current = Boolean(
                currentPlan &&
                plan.id === currentPlan.id &&
                billingPeriod === subscription?.billingPeriod
              );
              const isUpgrade = Boolean(
                currentPlan && plan.tier_level > currentPlan.tier_level
              );
              const isSamePlanDifferentPeriod = Boolean(
                currentPlan && plan.id === currentPlan.id && !current
              );
              const actionLabel = current
                ? t("billing.management.currentPlan")
                : isSamePlanDifferentPeriod
                  ? t("billing.management.reviewSubscription")
                  : currentPlan
                    ? isUpgrade
                      ? t("billing.management.reviewUpgrade")
                      : t("billing.management.reviewDowngrade") ||
                        t("billing.management.reviewSubscription")
                    : t("billing.management.reviewSubscription");

              return (
                <PlanCard
                  key={plan.id}
                  plan={plan}
                  currentPlan={current}
                  billingPeriod={billingPeriod}
                  onSelect={() => handlePlanSelection(plan)}
                  actionLabel={actionLabel}
                  actionDisabled={current || plan.isActive === false}
                />
              );
            })}

            <PlanCard
              key="custom"
              plan={customPlan}
              billingPeriod={billingPeriod}
              actionLabel={
                t("billing.plans.custom.action") || "Build Your Plan"
              }
              onSelect={() => {
                navigate(
                  `${routePaths.billingCustomPlan}?period=${encodeURIComponent(
                    billingPeriod
                  )}`
                );
              }}
            />
          </div>
        </section>

        <section className="billing-management-section">
          <header>
            <h2>{t("billing.management.comparison.title")}</h2>
            <p>{t("billing.management.comparison.subtitle")}</p>
          </header>
          <PlanComparisonTable
            plans={[...plans, customPlan]}
            currentPlanId={currentPlan?.id}
          />
        </section>
      </div>

      {notice && (
        <div className="billing-management-toast">
          <Toast
            variant={notice.variant}
            message={notice.message}
            onClose={() => setNotice(null)}
          />
        </div>
      )}
    </div>
  );
}
