import { ArrowLeft } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
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

const friendlyReviewReason = (reason) => {
  if (reason === "PRICE_ABOVE_AUTOMATIC_LIMIT") {
    return "This configuration is above the automatic plan-change price limit.";
  }
  if (reason === "UNVERIFIED_VENDOR_RATE") {
    return "One or more selected features use a vendor rate that still requires verification.";
  }
  if (reason?.startsWith("QUOTA_ABOVE_AUTOMATIC_LIMIT:")) {
    return `The requested ${reason.split(":")[1] || "feature"} quota requires manual review.`;
  }
  return "This configuration requires manual review.";
};

export function BillingCustomPlanPage() {
  const { t, locale, dir } = useI18n();
  const [params] = useSearchParams();

  const {
    data: configuratorResponse,
    error: configuratorError,
    isLoading
  } = useSWR(
    "custom-plan-configurator",
    billingApi.getCustomPlanConfigurator,
    swrOptions
  );
  const { data: subscriptionResponse, error: subscriptionError } = useSWR(
    "subscription-current",
    billingApi.getSubscription,
    swrOptions
  );

  const configurator = configuratorResponse?.data ?? null;
  const subscriptionApiError = subscriptionError
    ? getApiError(subscriptionError)
    : null;
  const hasActiveSubscription =
    Boolean(subscriptionResponse?.data) && !subscriptionApiError;

  const [billingPeriod, setBillingPeriod] = useState(
    params.get("period") || "monthly"
  );
  const [configuration, setConfiguration] = useState({});
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (!configurator?.features?.length) return;
    const next = {};
    for (const feature of configurator.features) {
      next[feature.id] = {
        selected: false,
        limitValue: feature.type === "limit" ? (feature.min ?? 0) : null
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
            ? `Custom-plan review requested successfully. Reference: ${data.quoteId}`
            : "Custom-plan review requested successfully."
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
        const effectiveDate = transition?.effectiveAt
          ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
              new Date(transition.effectiveAt)
            )
          : null;

        const scheduledMessage =
          transition?.effectiveTiming === "period_end"
            ? `Your Custom Plan has been created successfully and is scheduled to become active${effectiveDate ? ` on ${effectiveDate}` : " at the end of the current billing cycle"}. Your current ${transition?.currentPlan?.name || "plan"} remains active until then.`
            : null;

        setNotice({
          variant: "success",
          message:
            scheduledMessage ||
            response?.message ||
            "Your Custom Plan change has been applied successfully."
        });
        return;
      }

      if (data?.manualReviewRequired) {
        setNotice({
          variant: "success",
          message: data?.quoteId
            ? `Custom-plan review requested successfully. Reference: ${data.quoteId}`
            : "Custom-plan review requested successfully."
        });
        return;
      }

      if (data?.checkoutUrl) {
        window.location.assign(data.checkoutUrl);
        return;
      }

      throw new Error(
        "The custom-plan request completed without a checkout or subscription-change result."
      );
    } catch (error) {
      setNotice({ variant: "error", message: getApiError(error).message });
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
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
          title={t("billing.custom.title") || "Build Your Custom Plan"}
          subtitle={
            t("billing.custom.subtitle") ||
            "Choose the features and quotas that fit your business."
          }
        />
        <p className="billing-inline-error">
          {getApiError(configuratorError).message ||
            "Unable to load custom-plan options."}
        </p>
      </div>
    );
  }

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
        {t("billing.checkoutInApp.backToBilling") || "Back to plans"}
      </Link>

      <PageHeader
        title={t("billing.custom.title") || "Build Your Custom Plan"}
        subtitle={
          hasActiveSubscription
            ? "Configure the custom plan that should replace your current subscription."
            : t("billing.custom.subtitle") ||
              "Choose the features and quotas that fit your business."
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
                    {t("billing.custom.summaryTitle") || "Your Custom Plan"}
                  </h2>
                  <small>
                    {selectedFeatures.length} selected feature
                    {selectedFeatures.length === 1 ? "" : "s"}
                  </small>
                </div>
              </div>
            </header>

            {!selectedFeatures.length ? (
              <p className="ceopro-preview-notice">
                Choose at least one feature to calculate your price.
              </p>
            ) : previewLoading ? (
              <p className="ceopro-preview-notice">
                Calculating securely on the server...
              </p>
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
                    {t("billing.custom.estimatedPrice") || "Calculated price"}
                  </span>
                  <strong>{formatMoney(preview.price)}</strong>
                </div>

                {preview.months > 1 && (
                  <p className="ceopro-preview-notice">
                    {formatMoney(preview.monthlyPrice)} monthly base before the{" "}
                    {preview.discountPercent}% multi-month discount.
                  </p>
                )}

                {!preview.eligibleForInstantCheckout && (
                  <div className="ceopro-preview-notice" role="note">
                    <strong>Manual review required</strong>
                    <ul>
                      {(preview.manualReviewReasons || []).map((reason) => (
                        <li key={reason}>{friendlyReviewReason(reason)}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <Button
                  fullWidth
                  loading={submitting}
                  disabled={previewLoading || Boolean(previewError)}
                  onClick={submit}
                >
                  {!preview.eligibleForInstantCheckout
                    ? "Request Manual Review"
                    : hasActiveSubscription
                      ? "Confirm Custom Plan Change"
                      : "Continue to Checkout"}
                </Button>
              </>
            ) : null}
          </aside>
        </div>
      </section>
    </div>
  );
}
