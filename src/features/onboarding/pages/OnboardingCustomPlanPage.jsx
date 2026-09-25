import { useEffect, useMemo, useState } from "react";
import { Check, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { routePaths } from "../../../app/router/routePaths.js";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { billingApi, getApiError } from "../../billing/api/billingApi.js";
import { CustomPlanBuilder } from "../../billing/components/CustomPlanBuilder.jsx";
import SegmentedControl from "../../../shared/components/ui/SegmentedControl.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { OnboardingActions } from "../components/OnboardingActions.jsx";
import { OnboardingPageShell } from "../components/OnboardingPageShell.jsx";
import { useOnboardingStore } from "../store/onboardingStore.js";

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
  if (reason === "PRICE_ABOVE_AUTOMATIC_LIMIT")
    return "This configuration is above the instant-checkout price limit.";
  if (reason === "UNVERIFIED_VENDOR_RATE")
    return "One or more cost inputs require owner verification.";
  if (reason?.startsWith("QUOTA_ABOVE_AUTOMATIC_LIMIT:")) {
    return `The requested ${reason.split(":")[1] || "feature"} quota requires manual review.`;
  }
  return "This configuration requires manual review.";
};

export function OnboardingCustomPlanPage() {
  const navigate = useNavigate();
  const { t, locale } = useI18n();
  const {
    data: response,
    error,
    isLoading
  } = useSWR(
    "custom-plan-configurator",
    billingApi.getCustomPlanConfigurator,
    swrOptions
  );
  const configurator = response?.data ?? null;

  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const setBillingPeriod = useOnboardingStore(
    (state) => state.setBillingPeriod
  );
  const storedSelection = useOnboardingStore(
    (state) => state.customPlanSelection
  );
  const setStoredSelection = useOnboardingStore(
    (state) => state.setCustomPlanSelection
  );
  const setCustomPlanPreview = useOnboardingStore(
    (state) => state.setCustomPlanPreview
  );
  const setCustomCheckoutRequestId = useOnboardingStore(
    (state) => state.setCustomCheckoutRequestId
  );
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);

  const [configuration, setConfiguration] = useState({});
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [manualRequestLoading, setManualRequestLoading] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (!configurator?.features?.length) return;
    const stored = new Map(
      (storedSelection || []).map((item) => [item.featureId, item])
    );
    const next = {};

    for (const feature of configurator.features) {
      const previous = stored.get(feature.id);
      next[feature.id] = {
        selected: Boolean(previous),
        limitValue:
          feature.type === "limit"
            ? (previous?.limitValue ?? feature.min ?? 0)
            : null
      };
    }

    setConfiguration(next);
  }, [configurator, storedSelection]);

  useEffect(() => {
    const options = configurator?.billingOptions ?? [];
    if (!options.length) return;
    if (!options.some((option) => option.period === billingPeriod)) {
      setBillingPeriod(options[0].period);
    }
  }, [configurator, billingPeriod, setBillingPeriod]);

  const selectedFeatureDetails = useMemo(
    () =>
      (configurator?.features ?? [])
        .filter((feature) => configuration[feature.id]?.selected)
        .map((feature) => ({
          ...feature,
          limitValue:
            feature.type === "limit"
              ? (configuration[feature.id]?.limitValue ?? feature.min ?? 0)
              : null
        })),
    [configurator, configuration]
  );

  const selectedFeatures = useMemo(
    () =>
      selectedFeatureDetails.map((feature) => ({
        featureId: feature.id,
        ...(feature.type === "limit" ? { limitValue: feature.limitValue } : {})
      })),
    [selectedFeatureDetails]
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
        const result = await billingApi.previewCustomPlan({
          features: selectedFeatures,
          billingPeriod
        });
        if (!cancelled) setPreview(result?.data ?? null);
      } catch (requestError) {
        if (!cancelled) {
          setPreview(null);
          setPreviewError(getApiError(requestError).message);
        }
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }, 350);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [selectedFeatures, billingPeriod]);

  const updateFeature = (featureId, patch) => {
    setConfiguration((current) => ({
      ...current,
      [featureId]: { ...current[featureId], ...patch }
    }));
  };

  const continueFlow = async () => {
    if (!preview || !selectedFeatures.length) return;

    setStoredSelection(selectedFeatures);
    setCustomPlanPreview(preview);
    setPlanChoice(
      "custom",
      Number(configurator?.trialPeriodValue) > 0 ? "trial" : "paid"
    );

    if (preview.eligibleForInstantCheckout) {
      setCustomCheckoutRequestId(requestId());
      navigate(routePaths.onboardingPlanPayment);
      return;
    }

    setManualRequestLoading(true);
    try {
      const id = requestId();
      const result = await billingApi.requestCustomPlanManualReview({
        requestId: id,
        features: selectedFeatures,
        billingPeriod
      });
      const data = result?.data ?? result;
      setToast({
        variant: "success",
        message: data?.quoteId
          ? `Your request was saved for manual review (reference ${data.quoteId}).`
          : "Your custom-plan request was saved for manual review."
      });
    } catch (requestError) {
      setToast({
        variant: "error",
        message: getApiError(requestError).message
      });
    } finally {
      setManualRequestLoading(false);
    }
  };

  const formatMoney = (amount) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US", {
      style: "currency",
      currency: preview?.currency || configurator?.currency || "JOD"
    }).format(Number(amount || 0));

  const formatNumber = (value) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US").format(
      Number(value || 0)
    );

  if (isLoading) {
    return (
      <OnboardingPageShell wide step={5}>
        <Skeleton height="520px" variant="rectangular" />
      </OnboardingPageShell>
    );
  }

  if (error || !configurator) {
    return (
      <OnboardingPageShell
        wide
        step={5}
        title={t("billing.custom.title")}
        subtitle={t("billing.custom.subtitle")}
      >
        <p className="ceopro-preview-notice">
          {getApiError(error).message || "Unable to load custom-plan options."}
        </p>
        <OnboardingActions
          onBack={() => navigate(routePaths.onboardingPlan)}
          disabled
        />
      </OnboardingPageShell>
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

  const selectedOption = (configurator.billingOptions || []).find(
    (option) => option.period === billingPeriod
  );
  const months = preview?.months ?? selectedOption?.months ?? 1;
  const discountPercent =
    preview?.discountPercent ?? selectedOption?.discountPercent ?? 0;
  const subtotal = preview ? Number(preview.monthlyPrice || 0) * months : 0;
  const discountAmount = preview
    ? Math.max(0, subtotal - Number(preview.price || 0))
    : 0;

  return (
    <OnboardingPageShell
      wide
      step={5}
      title={t("billing.custom.title")}
      subtitle={t("billing.custom.subtitle")}
    >
      {toast && (
        <Toast
          message={toast.message}
          variant={toast.variant}
          onClose={() => setToast(null)}
        />
      )}

      <div className="ceopro-billing-period-row">
        <SegmentedControl
          name="custom-billing-period"
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

        <aside className="ceopro-plan-summary">
          <header>
            <div className="ceopro-plan-summary__identity">
              <span className="ceopro-plan-summary__icon">
                <Sparkles size={17} aria-hidden="true" />
              </span>
              <div>
                <h2>{t("billing.custom.summaryTitle")}</h2>
                <small>
                  {selectedFeatureDetails.length} selected feature
                  {selectedFeatureDetails.length === 1 ? "" : "s"}
                </small>
              </div>
            </div>
            <span>{t("common.custom")}</span>
          </header>

          {selectedFeatureDetails.length > 0 ? (
            <ul>
              {selectedFeatureDetails.map((feature) => {
                const name =
                  locale === "ar" && feature.name_ar
                    ? feature.name_ar
                    : feature.name;
                const unit =
                  locale === "ar"
                    ? feature.unit_ar || feature.unit
                    : feature.unit;

                return (
                  <li className="ceopro-plan-summary__feature" key={feature.id}>
                    <Check size={14} aria-hidden="true" />
                    <span>{name}</span>
                    {feature.type === "limit" && (
                      <strong>
                        {formatNumber(feature.limitValue)}
                        {unit ? ` ${unit}` : ""}
                      </strong>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="ceopro-preview-notice">
              Choose at least one feature to calculate your price.
            </p>
          )}

          {selectedFeatureDetails.length > 0 && (
            <div className="ceopro-plan-summary__price">
              <div>
                <span>{t("billing.payment.billingCycle")}</span>
                <strong>
                  {months === 1
                    ? t("billing.periods.monthly")
                    : t("billing.periods.monthCountLabel", { months })}
                </strong>
              </div>

              {preview && discountPercent > 0 && (
                <>
                  <div>
                    <span>{t("billing.payment.subtotal")}</span>
                    <strong>{formatMoney(subtotal)}</strong>
                  </div>
                  <div>
                    <span>
                      {t("billing.payment.discount", {
                        percent: discountPercent
                      })}
                    </span>
                    <strong>-{formatMoney(discountAmount)}</strong>
                  </div>
                </>
              )}

              <div>
                <span>{t("billing.payment.previewTotal")}</span>
                <strong>
                  {previewLoading
                    ? t("common.loading")
                    : preview
                      ? formatMoney(preview.price)
                      : "—"}
                </strong>
              </div>
            </div>
          )}

          {previewError && (
            <p
              className="ceopro-preview-notice"
              style={{ color: "var(--color-danger, #b42318)" }}
            >
              {previewError}
            </p>
          )}

          {preview && (
            <div className="ceopro-plan-summary__total">
              <span>{t("billing.custom.estimatedPrice")}</span>
              <strong>{formatMoney(preview.price)}</strong>
            </div>
          )}

          {preview && !preview.eligibleForInstantCheckout && (
            <div className="ceopro-plan-summary__helper" role="note">
              <strong>Manual review required</strong>
              {(preview.manualReviewReasons || []).map((reason) => (
                <span key={reason}>{friendlyReviewReason(reason)}</span>
              ))}
            </div>
          )}
        </aside>
      </div>

      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingPlan)}
        onContinue={continueFlow}
        continueLabel={
          preview && !preview.eligibleForInstantCheckout
            ? "Request Manual Review"
            : undefined
        }
        disabled={
          !preview ||
          previewLoading ||
          Boolean(previewError) ||
          !selectedFeatures.length
        }
        loading={manualRequestLoading}
      />
    </OnboardingPageShell>
  );
}
