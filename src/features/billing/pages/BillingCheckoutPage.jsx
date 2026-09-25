import { ArrowLeft, ArrowRight, LockKeyhole } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { billingApi, getApiError } from "../api/billingApi.js";

import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { CouponInput } from "../components/CouponInput.jsx";

import "../styles/Billing.css";
import "../styles/PlansSubscription.css";

const getPlanName = (plan, locale) => {
  if (!plan) return "";
  return locale === "ar" && plan.name_ar ? plan.name_ar : plan.name || "";
};
const getPlanPricingOptions = (plan = {}) => plan?.pricingOptions || [];
const getPricingPeriod = (option) => option?.period;
const getPricingMonths = (option) => option?.months || 1;
const getPricingTotal = (option, plan) =>
  option?.totalPrice ?? plan?.basePrice ?? 0;
const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

export function BillingCheckoutPage() {
  const { t, locale, dir } = useI18n();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [notice, setNotice] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [promoCode, setPromoCode] = useState("");
  const selectedPlanId = params.get("plan");
  const requestedPeriod = params.get("period");

  const {
    data: plansResponse,
    isLoading: plansLoading,
    error: plansError
  } = useSWR("subscription-plans", billingApi.getPlans, swrOptions);
  const {
    data: customPlansResponse,
    isLoading: customPlansLoading,
    error: customPlansError
  } = useSWR(
    "subscription-custom-plans",
    billingApi.getCustomPlans,
    swrOptions
  );
  const {
    data: subResponse,
    isLoading: subLoading,
    error: subscriptionError
  } = useSWR("subscription-current", billingApi.getSubscription, swrOptions);

  const formatCurrency = useMemo(
    () =>
      (amount, currency = "USD") =>
        new Intl.NumberFormat(locale, { style: "currency", currency }).format(
          amount || 0
        ),
    [locale]
  );
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }),
    [locale]
  );

  if (plansLoading || customPlansLoading || subLoading) {
    return (
      <div className="billing-checkout-loading">
        <Skeleton height="82px" variant="rectangular" />
        <Skeleton height="360px" variant="rectangular" />
      </div>
    );
  }

  if (plansError) {
    return (
      <EmptyState
        title={t("billing.checkoutInApp.errorTitle")}
        description={
          getApiError(plansError).message ||
          t("billing.checkoutInApp.errorDescription")
        }
        action={
          <Button onClick={() => navigate(routePaths.billingPlans)}>
            {t("billing.checkoutInApp.backToBilling")}
          </Button>
        }
      />
    );
  }

  const subscriptionApiError = subscriptionError
    ? getApiError(subscriptionError)
    : null;
  const subscriptionMissing =
    subscriptionApiError?.code === "SUBSCRIPTION_NOT_FOUND" ||
    subscriptionApiError?.status === 404;
  if (subscriptionError && !subscriptionMissing) {
    return (
      <EmptyState
        title={t("billing.checkoutInApp.errorTitle")}
        description={
          subscriptionApiError.message ||
          t("billing.checkoutInApp.errorDescription")
        }
        action={
          <Button onClick={() => navigate(routePaths.billing)}>
            {t("billing.checkoutInApp.backToBilling")}
          </Button>
        }
      />
    );
  }

  const plans = [
    ...(plansResponse?.data ?? []),
    ...(customPlansResponse?.data ?? [])
  ];
  const subscription = subResponse?.data ?? null;
  const currentPlan = subscription
    ? plans.find((plan) => plan.id === subscription.planId)
    : null;
  const hasActiveSubscription = Boolean(subscription);
  const isTrialingChange =
    hasActiveSubscription && subscription?.status === "trialing";
  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId);
  const pricingOption = getPlanPricingOptions(selectedPlan).find(
    (option) => getPricingPeriod(option) === requestedPeriod
  );
  const invalid =
    !selectedPlan || !pricingOption || selectedPlan.isActive === false;

  if (invalid) {
    return (
      <EmptyState
        title={t("billing.checkoutInApp.invalidTitle")}
        description={t("billing.checkoutInApp.invalidDescription")}
        action={
          <Link className="billing-link-button" to={routePaths.billingPlans}>
            {t("billing.checkoutInApp.backToBilling")}
          </Link>
        }
      />
    );
  }

  const currentPricingOption = getPlanPricingOptions(currentPlan).find(
    (option) => getPricingPeriod(option) === subscription?.billingPeriod
  );

  const submit = async () => {
    setIsSubmitting(true);
    setNotice(null);
    try {
      if (hasActiveSubscription) {
        const response = await billingApi.changePlan({
          planId: selectedPlan.id,
          billing_period: requestedPeriod
        });
        setNotice({
          variant: "success",
          message: response?.message || t("billing.checkoutInApp.changeSuccess")
        });
        return;
      }

      const response = await billingApi.createCheckout({
        planId: selectedPlan.id,
        billing_period: requestedPeriod,
        payment_method: "stripe",
        ...(promoCode.trim() ? { promoCode: promoCode.trim() } : {})
      });
      const checkoutUrl = response?.data?.checkoutUrl;
      if (!checkoutUrl)
        throw new Error("Checkout session was created without a redirect URL.");
      window.location.assign(checkoutUrl);
    } catch (requestError) {
      setNotice({
        variant: "error",
        message:
          getApiError(requestError).message ||
          t("billing.checkoutInApp.upgradeFailed")
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="billing-checkout-page" dir={dir}>
      <Link className="billing-back-link" to={routePaths.billingPlans}>
        <ArrowLeft className="ceopro-setup-direction-icon" size={15} />
        {t("billing.checkoutInApp.backToBilling")}
      </Link>

      <PageHeader
        title={t("billing.checkoutInApp.title")}
        subtitle={t("billing.checkoutInApp.subtitle")}
      />

      <div className="billing-checkout-layout">
        <Card className="billing-upgrade-review">
          <h2>{t("billing.checkoutInApp.summaryTitle")}</h2>
          <dl>
            {hasActiveSubscription && (
              <div>
                <dt>{t("billing.checkoutInApp.currentPlan")}</dt>
                <dd>
                  {currentPlan
                    ? getPlanName(currentPlan, locale)
                    : t("billing.management.unavailablePlanName")}
                  {currentPricingOption && currentPlan && (
                    <small>
                      {formatCurrency(
                        getPricingTotal(currentPricingOption, currentPlan),
                        currentPlan.currency
                      )}
                    </small>
                  )}
                </dd>
              </div>
            )}
            <div>
              <dt>{t("billing.checkoutInApp.newPlan")}</dt>
              <dd>{getPlanName(selectedPlan, locale)}</dd>
            </div>
            <div>
              <dt>{t("billing.checkoutInApp.billingPeriod")}</dt>
              <dd>
                {getPricingMonths(pricingOption) === 1
                  ? t("billing.periods.monthly")
                  : t("billing.periods.monthCountLabel", {
                      months: getPricingMonths(pricingOption)
                    })}
              </dd>
            </div>
            <div>
              <dt>{t("billing.checkoutInApp.configuredPrice")}</dt>
              <dd>
                {formatCurrency(
                  getPricingTotal(pricingOption, selectedPlan),
                  selectedPlan.currency
                )}
              </dd>
            </div>
            {hasActiveSubscription && subscription?.currentPeriodEnd && (
              <div>
                <dt>{t("billing.checkoutInApp.currentRenewal")}</dt>
                <dd>
                  {dateFormatter.format(
                    new Date(subscription.currentPeriodEnd)
                  )}
                </dd>
              </div>
            )}
            <div>
              <dt>{t("billing.checkoutInApp.effectiveDate")}</dt>
              <dd>{t("billing.checkoutInApp.providerDetermined")}</dd>
            </div>
          </dl>

          {!hasActiveSubscription && (
            <CouponInput
              planId={selectedPlan.id}
              value={promoCode}
              onChange={setPromoCode}
              disabled={isSubmitting}
            />
          )}
        </Card>

        <aside className="billing-payment-boundary">
          <span>
            <LockKeyhole size={24} />
          </span>
          <h2>{t("billing.checkoutInApp.securePayment")}</h2>
          <p>
            {isTrialingChange
              ? t("billing.checkoutInApp.trialUpgradeDescription")
              : hasActiveSubscription
                ? t("billing.checkoutInApp.planChangeDescription")
                : t("billing.checkoutInApp.securePaymentDescription")}
          </p>
          <Button
            fullWidth
            trailingIcon={
              <ArrowRight className="ceopro-setup-direction-icon" size={15} />
            }
            loading={isSubmitting}
            loadingLabel={t("billing.checkoutInApp.preparing")}
            onClick={submit}
          >
            {hasActiveSubscription
              ? t("billing.checkoutInApp.confirmChange") ||
                "Confirm Plan Change"
              : t("billing.checkoutInApp.continue")}
          </Button>
          <small>{t("billing.checkoutInApp.noPaymentStored")}</small>
        </aside>
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
