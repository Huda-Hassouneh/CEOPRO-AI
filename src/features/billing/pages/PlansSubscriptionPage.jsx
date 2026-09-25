import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { billingApi, getApiError } from "../api/billingApi.js";

import Modal from "../../../shared/components/ui/Modal.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";

import { CurrentPlanCard } from "../components/CurrentPlanCard.jsx";
import { InvoiceHistoryTable } from "../components/InvoiceHistoryTable.jsx";
import { UsageLimitGrid } from "../components/UsageLimitGrid.jsx";
import { UpgradeRecommendation } from "../components/UpgradeRecommendation.jsx";
import { getUpgradeRecommendation } from "../utils/subscriptionRecommendations.js";

import "../styles/Billing.css";
import "../styles/PlansSubscription.css";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

const patchSubscriptionResponse = (response, patch) => {
  if (!response) return response;
  if (
    response.data &&
    typeof response.data === "object" &&
    !Array.isArray(response.data)
  ) {
    return { ...response, data: { ...response.data, ...patch } };
  }
  return { ...response, ...patch };
};

export function PlansSubscriptionPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [isCancelAlertOpen, setIsCancelAlertOpen] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isResuming, setIsResuming] = useState(false);
  const [notice, setNotice] = useState(null);

  const {
    data: plansResponse,
    isLoading: plansLoading,
    error: plansError
  } = useSWR("subscription-plans", billingApi.getPlans, swrOptions);
  const { data: customPlansResponse, isLoading: customPlansLoading } = useSWR(
    "subscription-custom-plans",
    billingApi.getCustomPlans,
    swrOptions
  );
  const {
    data: coreSubResponse,
    isLoading: coreSubLoading,
    error: coreSubError,
    mutate: mutateCoreSubscription
  } = useSWR("subscription-current", billingApi.getSubscription, swrOptions);
  const hasSubscriptionResponse = Boolean(coreSubResponse?.data ?? coreSubResponse);
  const {
    data: usageResponse,
    isLoading: usageLoading,
    error: usageError
  } = useSWR(
    hasSubscriptionResponse ? "subscription-current-usage" : null,
    hasSubscriptionResponse ? billingApi.getSubscriptionUsage : null,
    swrOptions
  );
  const {
    data: invoicesResponse,
    isLoading: invoicesLoading,
    error: invoicesError
  } = useSWR(
    hasSubscriptionResponse ? "subscription-invoices" : null,
    hasSubscriptionResponse ? billingApi.getInvoices : null,
    swrOptions
  );
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }),
    [locale]
  );

  if (plansLoading || customPlansLoading || coreSubLoading) {
    return (
      <div className="billing-management-loading" aria-busy="true">
        <Skeleton
          height="82px"
          variant="rectangular"
          style={{ marginBottom: "20px" }}
        />
        <Skeleton height="360px" variant="rectangular" />
      </div>
    );
  }

  if (plansError) {
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.management.title")}
          subtitle={t("billing.management.subtitle")}
        />
        <p className="billing-inline-error">
          {getApiError(plansError).message}
        </p>
      </div>
    );
  }

  const coreError = coreSubError ? getApiError(coreSubError) : null;
  const noSubscription =
    coreError?.code === "SUBSCRIPTION_NOT_FOUND" || coreError?.status === 404;
  if (coreSubError && !noSubscription) {
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.management.title")}
          subtitle={t("billing.management.subtitle")}
        />
        <p className="billing-inline-error">{coreError.message}</p>
      </div>
    );
  }

  const plans = [
    ...(plansResponse?.data ?? []),
    ...(customPlansResponse?.data ?? [])
  ];
  const coreSub = coreSubResponse?.data ?? null;
  const usageData = usageResponse ?? null;
  const invoices = invoicesResponse?.data ?? [];
  const subscriptionPlanFallback = coreSub?.plan
    ? (() => {
        const basePrice = Number(coreSub.plan.price ?? 0);
        const pricingOptions = (coreSub.plan.billingOptions ?? []).map((option) => {
          const months = Number(option?.months ?? 1);
          const discountPercent = Number(option?.discountPercent ?? 0);
          const totalPrice = basePrice * months * (1 - discountPercent / 100);
          return {
            ...option,
            months,
            discountPercent,
            totalPrice,
            monthlyEquivalent: totalPrice / Math.max(1, months)
          };
        });

        return {
          ...coreSub.plan,
          basePrice,
          pricingOptions
        };
      })()
    : null;
  const rawCurrentPlan = coreSub
    ? plans.find((plan) => plan.id === coreSub.planId) ?? subscriptionPlanFallback
    : null;
  const currentPlan = rawCurrentPlan
    ? {
        ...rawCurrentPlan,
        displayName:
          locale === "ar" && rawCurrentPlan.name_ar
            ? rawCurrentPlan.name_ar
            : rawCurrentPlan.name,
        displayDescription:
          locale === "ar" && rawCurrentPlan.description_ar
            ? rawCurrentPlan.description_ar
            : rawCurrentPlan.description
      }
    : coreSub
      ? {
          id: coreSub.planId,
          displayName:
            usageData?.planName || t("billing.management.unavailablePlanName"),
          pricingOptions: [],
          features: usageData?.features ?? {}
        }
      : null;
  const features = {
    ...(currentPlan?.features ?? {}),
    ...(usageData?.features ?? {})
  };
  const unifiedSubscription = coreSub
    ? {
        ...coreSub,
        renewsAt: coreSub.currentPeriodEnd,
        billingPeriod: coreSub.billingPeriod || "monthly",
        usage: usageData?.usage ?? {},
        limits: usageData?.limits ?? {},
        features
      }
    : null;
  const hasActiveSubscription = Boolean(coreSub);
  const isPendingCancellation = Boolean(coreSub?.cancelAtPeriodEnd);

  if (!hasActiveSubscription) {
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.management.title")}
          subtitle={t("billing.management.subtitle")}
        />
        <EmptyState
          title={
            t("billing.management.missingTitle") || "No Active Subscription"
          }
          description={
            t("billing.management.missingDescription") ||
            "You are not currently subscribed to any plan."
          }
          action={
            <div className="billing-empty-actions">
              <Button onClick={() => navigate(routePaths.billingPlans)}>
                {t("billing.management.comparePlansAction") ||
                  "View Available Plans"}
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  const reconcileCancellation = async (expectedCancelAtPeriodEnd) => {
    for (const delay of [400, 800, 1500, 2500]) {
      await wait(delay);
      try {
        const freshResponse = await billingApi.getSubscription();
        const freshSubscription = freshResponse?.data ?? freshResponse;
        if (
          Boolean(freshSubscription?.cancelAtPeriodEnd) ===
          expectedCancelAtPeriodEnd
        ) {
          await mutateCoreSubscription(freshResponse, { revalidate: false });
          return true;
        }
      } catch {
        // The optimistic state remains visible until a later successful revalidation.
      }
    }
    return false;
  };

  const handleConfirmCancel = async () => {
    setIsCancelAlertOpen(false);
    setIsCancelling(true);
    const previousSubscription = coreSubResponse;
    await mutateCoreSubscription(
      (current) =>
        patchSubscriptionResponse(current, { cancelAtPeriodEnd: true }),
      { revalidate: false }
    );

    try {
      await billingApi.cancelSubscription();
      setNotice({
        variant: "success",
        message:
          t("billing.management.cancelSuccess") ||
          "Subscription cancellation scheduled successfully."
      });
      void reconcileCancellation(true);
    } catch (error) {
      await mutateCoreSubscription(previousSubscription, { revalidate: false });
      setNotice({
        variant: "error",
        message:
          getApiError(error).message || t("billing.management.cancelError")
      });
    } finally {
      setIsCancelling(false);
    }
  };

  const handleResumeSubscription = async () => {
    setIsResuming(true);
    const previousSubscription = coreSubResponse;
    await mutateCoreSubscription(
      (current) =>
        patchSubscriptionResponse(current, { cancelAtPeriodEnd: false }),
      { revalidate: false }
    );

    try {
      await billingApi.resumeSubscription();
      setNotice({
        variant: "success",
        message:
          t("billing.management.resumeSuccess") ||
          "Subscription resumed successfully."
      });
      void reconcileCancellation(false);
    } catch (error) {
      await mutateCoreSubscription(previousSubscription, { revalidate: false });
      setNotice({
        variant: "error",
        message:
          getApiError(error).message || t("billing.management.resumeError")
      });
    } finally {
      setIsResuming(false);
    }
  };

  const rawRecommendation = getUpgradeRecommendation(unifiedSubscription);
  const recommendation = rawRecommendation
    ? {
        titleKey: rawRecommendation.contextual
          ? `billing.management.context.${rawRecommendation.key}.title`
          : `billing.management.recommendation.${rawRecommendation.type}Title`,
        descriptionKey: rawRecommendation.contextual
          ? `billing.management.context.${rawRecommendation.key}.description`
          : `billing.management.recommendation.${rawRecommendation.type}Description`,
        values: rawRecommendation.key
          ? {
              metric: t(
                `billing.management.usageLabels.${rawRecommendation.key}`
              ),
              used: new Intl.NumberFormat(locale, {
                maximumFractionDigits: 1
              }).format(unifiedSubscription.usage[rawRecommendation.key] || 0),
              limit: new Intl.NumberFormat(locale, {
                maximumFractionDigits: 1
              }).format(unifiedSubscription.limits[rawRecommendation.key] || 0)
            }
          : {}
      }
    : null;

  return (
    <div className="billing-management-page" dir={dir}>
      <PageHeader
        title={t("billing.management.title")}
        subtitle={t("billing.management.subtitle")}
      />

      <div className="tab-content-fade-in">
        <CurrentPlanCard
          currentSubscription={coreSub}
          subscription={unifiedSubscription}
          plan={currentPlan}
          locale={locale}
          t={t}
          isPendingCancellation={isPendingCancellation}
          formatDate={(value) => dateFormatter.format(new Date(value))}
        />

        <div className="billing-management-actions">

          {isPendingCancellation ? (
            <Button onClick={handleResumeSubscription} loading={isResuming}>
              {t("billing.management.resumeSubscription") ||
                "Resume Subscription"}
            </Button>
          ) : (
            <>
              <button
                onClick={() => setIsCancelAlertOpen(true)}
                disabled={isCancelling}
                className="billing-cancel-link"
              >
                {isCancelling
                  ? t("billing.management.cancelling") || "Cancelling..."
                  : t("billing.management.cancelSubscription") ||
                    "Cancel Subscription"}
              </button>
              <Button
                variant="outline"
                onClick={() => navigate(routePaths.billingPlans)}
              >
                {t("billing.management.changePlan") || "Upgrade or Change Plan"}
              </Button>
            </>
          )}
        </div>

        <section className="billing-management-section">
          <header>
            <h2>{t("billing.management.usageTitle") || "Current Usage"}</h2>
            <p>
              {t("billing.management.usageSubtitle") ||
                "Monitor your resource consumption"}
            </p>
          </header>
          {usageLoading ? (
            <Skeleton height="180px" variant="rectangular" />
          ) : usageError ? (
            <p className="billing-usage-unavailable">
              {getApiError(usageError).message}
            </p>
          ) : (
            <UsageLimitGrid
              features={features}
              usage={unifiedSubscription.usage}
              limits={unifiedSubscription.limits}
              locale={locale}
              t={t}
            />
          )}
        </section>

        {!isPendingCancellation && recommendation && (
          <UpgradeRecommendation
            recommendation={recommendation}
            onCompare={() => navigate(routePaths.billingPlans)}
            t={t}
          />
        )}

        <section className="billing-management-section">
          <header>
            <h2>{t("billing.invoices.title") || "Billing History"}</h2>
            <p>
              {t("billing.invoices.subtitle") ||
                "Successful paid invoices for this subscription."}
            </p>
          </header>
          {invoicesLoading ? (
            <Skeleton height="170px" variant="rectangular" />
          ) : invoicesError ? (
            <p className="billing-usage-unavailable">
              {getApiError(invoicesError).message}
            </p>
          ) : (
            <InvoiceHistoryTable invoices={invoices} locale={locale} t={t} />
          )}
        </section>
      </div>

      <Modal
        isOpen={isCancelAlertOpen}
        onClose={() => setIsCancelAlertOpen(false)}
        title={
          t("billing.management.cancelSubscription") || "Cancel Subscription?"
        }
        maxWidth="430px"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setIsCancelAlertOpen(false)}
            >
              {t("common.keep") || "No, Keep It"}
            </Button>
            <Button
              onClick={handleConfirmCancel}
              disabled={isCancelling}
              style={{
                background: "var(--ceopro-error)",
                borderColor: "var(--ceopro-error)"
              }}
            >
              {t("billing.management.confirmCancel") || "Yes, Cancel"}
            </Button>
          </>
        }
      >
        <p>
          {t("billing.management.cancelConfirmMessage") ||
            "Are you sure you want to cancel? You will retain access until the end of the current billing period."}
        </p>
      </Modal>

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
