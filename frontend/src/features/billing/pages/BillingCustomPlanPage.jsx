import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import SegmentedControl from "../../../shared/components/ui/SegmentedControl.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { billingApi, getApiError } from "../api/billingApi.js";
import { CustomPlanBuilder } from "../components/CustomPlanBuilder.jsx";
import { SubscriptionRecoveryBanner } from "../components/SubscriptionRecoveryBanner.jsx";
import { useSubscriptionRecovery } from "../hooks/useSubscriptionRecovery.js";
import { isRecoverableSubscriptionStatus } from "../utils/subscriptionStatus.js";
import {
  getPlanChangeNotice,
  getPlanChangeRecoveryLabel,
  isKnownPlanChangeState,
  isPlanChangePaymentRecoveryState
} from "../utils/planChangeResult.js";

import "../styles/Billing.css";
import "../styles/PlansSubscription.css";

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

const requestId = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
};

const friendlyReviewReason = (reason, t) => {
  const key = reason === "PRICE_ABOVE_AUTOMATIC_LIMIT" ? "price"
    : reason === "UNVERIFIED_VENDOR_RATE" ? "vendorRate"
    : reason?.startsWith("QUOTA_ABOVE_AUTOMATIC_LIMIT:") ? "quota" : "default";
  return t(`billing.custom.manualReview.reasons.${key}`);
};

export function BillingCustomPlanPage() {
  const { t, locale, dir } = useI18n();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const recovery = useSubscriptionRecovery();

  const {
    data: configuratorResponse,
    error: configuratorError,
    isLoading
  } = useSWR(
    "custom-plan-configurator",
    billingApi.getCustomPlanConfigurator,
    swrOptions
  );
  const {
    data: subscriptionResponse,
    error: subscriptionError,
    isLoading: subscriptionLoading
  } = useSWR(
    "subscription-current",
    billingApi.getSubscription,
    swrOptions
  );

  const configurator = configuratorResponse?.data ?? null;
  const subscriptionApiError = subscriptionError
    ? getApiError(subscriptionError)
    : null;
  const subscriptionMissing =
    subscriptionApiError?.status === 404 ||
    subscriptionApiError?.code === "SUBSCRIPTION_NOT_FOUND";
  const currentSubscription = subscriptionResponse?.data ?? null;
  const hasCurrentSubscription =
    Boolean(currentSubscription) && !subscriptionApiError;
  const needsRecovery = isRecoverableSubscriptionStatus(
    currentSubscription?.status
  );

  const [billingPeriod, setBillingPeriod] = useState(
    params.get("period") || "monthly"
  );
  const [configuration, setConfiguration] = useState({});
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState(null);
  const [planChangeResult, setPlanChangeResult] = useState(null);

  useEffect(() => {
    if (!configurator?.features?.length) return;
    const next = {};
    for (const feature of configurator.features) {
      next[feature.id] = {
        selected: false,
        limitValue: feature.type === "limit" ? (feature.min ?? 0) : null,
        ...(feature.configuration?.monitoringCadence
          ? {
              configuration: {
                monitoringFrequencyMinutes:
                  feature.configuration.monitoringCadence.defaultMinutes
              }
            }
          : {})
      };
    }
    setConfiguration(next);
  }, [configurator]);

  useEffect(() => {
    const options = configurator?.billingOptions ?? [];
    if (!options.length) return;
    if (!options.some((option) => option.period === billingPeriod)) {
      setBillingPeriod(options[0].period);
    }
  }, [billingPeriod, configurator]);

  const selectedFeatures = useMemo(
    () =>
      (configurator?.features ?? [])
        .filter((feature) => configuration[feature.id]?.selected)
        .map((feature) => ({
          featureId: feature.id,
          ...(feature.type === "limit"
            ? {
                limitValue:
                  configuration[feature.id]?.limitValue ?? feature.min ?? 0
              }
            : {}),
          ...(feature.configuration?.monitoringCadence
            ? {
                configuration: configuration[feature.id]?.configuration
              }
            : {})
        })),
    [configuration, configurator]
  );

  useEffect(() => {
    if (!selectedFeatures.length || !billingPeriod) {
      setPreview(null);
      setPreviewError("");
      return undefined;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      setPreviewLoading(true);
      setPreviewError("");
      try {
        const response = await billingApi.previewCustomPlan({
          features: selectedFeatures,
          billingPeriod
        });
        if (!cancelled) setPreview(response?.data ?? response ?? null);
      } catch (error) {
        if (!cancelled) {
          setPreview(null);
          setPreviewError(getApiError(error).message);
        }
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }, 350);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [billingPeriod, selectedFeatures]);

  const updateFeature = (featureId, patch) => {
    setConfiguration((current) => ({
      ...current,
      [featureId]: {
        ...current[featureId],
        ...patch
      }
    }));
  };

  const formatMoney = (amount) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US", {
      style: "currency",
      currency: preview?.currency || configurator?.currency || "JOD"
    }).format(Number(amount || 0));

  const submit = async () => {
    if (!preview || !selectedFeatures.length) return;

    setSubmitting(true);
    setNotice(null);
    setPlanChangeResult(null);
    try {
      const payload = {
        requestId: requestId(),
        features: selectedFeatures,
        billingPeriod
      };

      if (!preview.eligibleForInstantCheckout) {
        const response =
          await billingApi.requestCustomPlanManualReview(payload);
        const data = response?.data ?? response;
        setNotice({
          variant: "success",
          message: data?.quoteId
            ? t("billing.custom.reviewRequestedReference", { reference: data.quoteId })
            : t("interfaceCopy.customPlanReviewRequestedSuccessfully")
        });
        return;
      }

      const response = await billingApi.checkoutCustomPlan({
        ...payload,
        paymentMethod: "stripe"
      });
      const data = response?.data ?? response;

      if (data?.subscriptionChanged) {
        const transition = data?.transition;

        if (!isKnownPlanChangeState(transition?.state)) {
          throw new Error(
            t("billing.checkoutInApp.planChangeStates.unknown")
          );
        }

        setPlanChangeResult(transition);
        setNotice(
          getPlanChangeNotice(transition, t, {
            trialing: currentSubscription?.status === "trialing"
          })
        );
        return;
      }

      if (data?.manualReviewRequired) {
        setNotice({
          variant: "success",
          message: data?.quoteId
            ? t("billing.custom.reviewRequestedReference", { reference: data.quoteId })
            : t("interfaceCopy.customPlanReviewRequestedSuccessfully")
        });
        return;
      }

      if (data?.checkoutUrl) {
        window.location.assign(data.checkoutUrl);
        return;
      }

      throw new Error(
        t("interfaceCopy.theCustomPlanRequestCompletedWithoutACheckoutOrSubscriptionChangeResult")
      );
    } catch (error) {
      setNotice({ variant: "error", message: getApiError(error).message });
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading || subscriptionLoading) {
    return (
      <div className="billing-checkout-loading">
        <Skeleton height="520px" variant="rectangular" />
      </div>
    );
  }

  if (configuratorError || !configurator) {
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.custom.title")}
          subtitle={
            t("billing.custom.subtitle")
          }
        />
        <p className="billing-inline-error">
          {getApiError(configuratorError).message ||
            t("interfaceCopy.unableToLoadCustomPlanOptions")}
        </p>
      </div>
    );
  }

  if (subscriptionError && !subscriptionMissing) {
    return (
      <div className="billing-management-page" dir={dir}>
        <PageHeader
          title={t("billing.custom.title")}
          subtitle={t("billing.custom.subtitle")}
        />
        <p className="billing-inline-error">
          {subscriptionApiError?.message || t("billing.recovery.failed")}
        </p>
      </div>
    );
  }

  if (needsRecovery) {
    return (
      <div className="billing-management-page" dir={dir}>
        <Link className="billing-back-link" to={routePaths.billing}>
          <ArrowLeft className="ceopro-setup-direction-icon" size={15} />
          {t("billing.checkoutInApp.backToBilling")}
        </Link>

        <PageHeader
          title={t("billing.custom.title")}
          subtitle={t("billing.custom.subtitle")}
        />

        <SubscriptionRecoveryBanner
          status={currentSubscription.status}
          onRecover={recovery.recover}
          recovering={recovery.isRecovering}
          error={recovery.error}
        />
      </div>
    );
  }

  const planChangeNeedsPaymentAction =
    isPlanChangePaymentRecoveryState(planChangeResult?.state) &&
    Boolean(planChangeResult?.recoveryUrl);
  const planChangeRecoveryLabel = planChangeNeedsPaymentAction
    ? getPlanChangeRecoveryLabel(planChangeResult?.state, t)
    : null;

  const handlePlanChangePrimaryAction = () => {
    if (planChangeNeedsPaymentAction && planChangeResult?.recoveryUrl) {
      window.location.assign(planChangeResult.recoveryUrl);
      return;
    }

    navigate(routePaths.billing);
  };

  const periodOptions = (configurator.billingOptions || []).map((option) => ({
    value: option.period,
    label:
      option.months === 1
        ? t("billing.periods.monthly")
        : t("billing.periods.monthCountLabel", { months: option.months }),
    badge:
      option.discountPercent > 0
        ? t("billing.periods.savePercent", { percent: option.discountPercent })
        : undefined
  }));

  return (
    <div className="billing-management-page" dir={dir}>
      <Link className="billing-back-link" to={routePaths.billingPlans}>
        <ArrowLeft className="ceopro-setup-direction-icon" size={15} />
        {t("billing.checkoutInApp.backToBilling")}
      </Link>

      <PageHeader
        title={t("billing.custom.title")}
        subtitle={
          hasCurrentSubscription
            ? "Configure the custom plan that should replace your current subscription."
            : t("billing.custom.subtitle")
        }
      />

      {notice && (
        <div className="billing-management-toast">
          <Toast
            variant={notice.variant}
            message={notice.message}
            onClose={() => setNotice(null)}
          />
        </div>
      )}

      <section className="billing-management-section">
        <div className="ceopro-billing-period-row">
          <SegmentedControl
            name="billing-custom-period"
            value={billingPeriod}
            options={periodOptions}
            onChange={setBillingPeriod}
            ariaLabel={t("billing.periods.label")}
          />
        </div>

        <div className="ceopro-custom-plan-layout">
          <CustomPlanBuilder
            features={configurator.features}
            configuration={configuration}
            onChange={updateFeature}
          />

          <aside className="ceopro-plan-summary" aria-live="polite">
            <header>
              <div className="ceopro-plan-summary__identity">
                <div>
                  <h2>
                    {t("billing.custom.summaryTitle")}
                  </h2>
                  <small>
                    {t("billing.custom.selectedFeatureCount", { count: new Intl.NumberFormat(locale).format(selectedFeatures.length) })}
                  </small>
                </div>
              </div>
            </header>

            {!selectedFeatures.length ? (
              <p className="ceopro-preview-notice">{t("interfaceCopy.chooseAtLeastOneFeatureToCalculateYourPrice")}</p>
            ) : previewLoading ? (
              <p className="ceopro-preview-notice">{t("interfaceCopy.calculatingSecurelyOnTheServer")}</p>
            ) : previewError ? (
              <p
                className="ceopro-preview-notice"
                style={{ color: "var(--color-danger, #b42318)" }}
              >
                {previewError}
              </p>
            ) : preview ? (
              <>
                <div className="ceopro-plan-summary__total">
                  <span>
                    {t("billing.custom.estimatedPrice")}
                  </span>
                  <strong>{formatMoney(preview.price)}</strong>
                </div>

                {preview.months > 1 && (
                  <p className="ceopro-preview-notice">
                    {t("billing.custom.monthlyBaseBeforeDiscount", { price: formatMoney(preview.monthlyPrice), percent: new Intl.NumberFormat(locale).format(preview.discountPercent) })}
                  </p>
                )}

                {!preview.eligibleForInstantCheckout && (
                  <div className="ceopro-preview-notice" role="note">
                    <strong>{t("interfaceCopy.manualReviewRequired")}</strong>
                    <ul>
                      {(preview.manualReviewReasons || []).map((reason) => (
                        <li key={reason}>{friendlyReviewReason(reason, t)}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <Button
                  fullWidth
                  loading={submitting}
                  disabled={previewLoading || Boolean(previewError)}
                  onClick={planChangeResult ? handlePlanChangePrimaryAction : submit}
                >
                  {planChangeRecoveryLabel
                    ? planChangeRecoveryLabel
                    : planChangeResult
                      ? t("billing.checkoutInApp.backToBilling")
                      : !preview.eligibleForInstantCheckout
                        ? t("interfaceCopy.requestManualReview")
                        : hasCurrentSubscription
                          ? t("interfaceCopy.confirmCustomPlanChange")
                          : t("interfaceCopy.continueToCheckout")}
                </Button>
              </>
            ) : null}
          </aside>
        </div>
      </section>
    </div>
  );
}
