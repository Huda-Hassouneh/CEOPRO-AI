import { useMemo, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import useSWR from 'swr';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { billingApi, getApiError } from '../../billing/api/billingApi.js';
import { CouponInput } from '../../billing/components/CouponInput.jsx';
import { PaymentMethodSelector } from '../../billing/components/PaymentMethodSelector.jsx';
import { PlanSummaryCard } from '../../billing/components/PlanSummaryCard.jsx';
import { useCheckout } from '../../billing/hooks/useCheckout.js';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };

export function OnboardingPaymentPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [toast, setToast] = useState(null);
  const [promoCode, setPromoCode] = useState('');
  const [customPending, setCustomPending] = useState(false);
  const selectedPlan = useOnboardingStore((state) => state.selectedPlan);
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const customPlanSelection = useOnboardingStore((state) => state.customPlanSelection);
  const customPlanPreview = useOnboardingStore((state) => state.customPlanPreview);
  const customCheckoutRequestId = useOnboardingStore((state) => state.customCheckoutRequestId);
  const setCustomCheckoutRequestId = useOnboardingStore((state) => state.setCustomCheckoutRequestId);
  const clearCustomCheckoutRequestId = useOnboardingStore((state) => state.clearCustomCheckoutRequestId);
  const checkout = useCheckout();
  const isCustom = selectedPlan === 'custom';

  const { data: response, error, isLoading } = useSWR(
    isCustom ? null : 'subscription-plans',
    billingApi.getPlans,
    swrOptions,
  );

  const plans = useMemo(() => {
    const rawPlans = response?.data ?? [];
    return rawPlans.map((plan) => ({
      ...plan,
      displayName: locale === 'ar' && plan.name_ar ? plan.name_ar : plan.name,
      displayDescription:
        locale === 'ar' && plan.description_ar ? plan.description_ar : plan.description,
    }));
  }, [response, locale]);

  const customPlanDetails = useMemo(() => {
    if (!isCustom || !customPlanPreview) return null;
    const features = Object.fromEntries((customPlanPreview.features || []).map((feature) => [
      feature.code,
      {
        ...feature,
        limitValue: feature.type === 'boolean' ? null : feature.limitValue,
      },
    ]));
    return {
      id: 'custom',
      name: t('billing.plans.custom.name') || 'Custom',
      displayName: t('billing.plans.custom.name') || 'Custom',
      description: t('billing.plans.custom.description') || 'Your configured plan',
      displayDescription: t('billing.plans.custom.description') || 'Your configured plan',
      currency: customPlanPreview.currency,
      basePrice: customPlanPreview.monthlyPrice,
      trialPeriodValue: customPlanPreview.trialPeriodValue || 0,
      features,
      pricingOptions: [{
        period: customPlanPreview.billingPeriod,
        months: customPlanPreview.months || 1,
        discountPercent: customPlanPreview.discountPercent || 0,
        totalPrice: customPlanPreview.price,
        monthlyEquivalent: customPlanPreview.monthlyPrice,
      }],
    };
  }, [isCustom, customPlanPreview, t]);

  const activePlanDetails = isCustom
    ? customPlanDetails
    : plans.find((plan) => plan.id === selectedPlan);
  const checkoutMode = Number(activePlanDetails?.trialPeriodValue) > 0 ? 'trial' : 'paid';
  const pricingOption = activePlanDetails?.pricingOptions?.find(
    (option) => option.period === billingPeriod,
  );

  const completeCheckout = async () => {
    if (!activePlanDetails || !pricingOption) return;
    setToast(null);

    if (isCustom) {
      if (!customPlanSelection?.length) {
        navigate(routePaths.onboardingPlanCustom);
        return;
      }
      setCustomPending(true);
      try {
        let requestId = customCheckoutRequestId;
        if (!requestId) {
          requestId = globalThis.crypto?.randomUUID?.();
          if (!requestId) throw new Error('Unable to create a secure checkout request identifier.');
          setCustomCheckoutRequestId(requestId);
        }
        const responseData = await billingApi.checkoutCustomPlan({
          requestId,
          features: customPlanSelection,
          billingPeriod,
          paymentMethod: 'stripe',
        });
        const result = responseData?.data ?? responseData;
        if (result?.manualReviewRequired) {
          setToast({
            message: 'Pricing conditions changed and this configuration now requires manual review. Return to the custom-plan builder to submit it.',
            variant: 'info',
          });
          return;
        }
        if (!result?.checkoutUrl) throw new Error('Checkout URL was not returned by the server.');
        window.location.assign(result.checkoutUrl);
      } catch (requestError) {
        const apiError = getApiError(requestError);
        if (apiError.code === 'RESOURCE_ALREADY_EXISTS') {
          clearCustomCheckoutRequestId();
        }
        setToast({
          message: apiError.message || t('billing.payment.error'),
          variant: 'error',
        });
      } finally {
        setCustomPending(false);
      }
      return;
    }

    try {
      const result = await checkout.mutateAsync({
        planId: activePlanDetails.id,
        billingPeriod,
        method: 'stripe',
        promoCode: promoCode.trim() || undefined,
      });

      if (result.status === 'redirecting') {
        setToast({
          message: t('billing.payment.redirecting') || 'Redirecting to secure checkout...',
          variant: 'info',
        });
      }
    } catch (requestError) {
      setToast({
        message: getApiError(requestError).message || t('billing.payment.error'),
        variant: 'error',
      });
    }
  };

  if (!isCustom && isLoading) {
    return (
      <OnboardingPageShell wide showProgress={false}>
        <Skeleton height="500px" variant="rectangular" />
      </OnboardingPageShell>
    );
  }

  if ((!isCustom && error) || !activePlanDetails || !pricingOption) {
    return (
      <OnboardingPageShell wide showProgress={false}>
        <EmptyState
          title={t('billing.checkoutInApp.invalidTitle')}
          description={t('billing.checkoutInApp.invalidDescription')}
          action={(
            <Link className="billing-link-button" to={isCustom ? routePaths.onboardingPlanCustom : routePaths.onboardingPlan}>
              {t('billing.payment.backToPlans')}
            </Link>
          )}
        />
      </OnboardingPageShell>
    );
  }

  return (
    <OnboardingPageShell wide showProgress={false}>
      {toast && (
        <div style={{ position: 'fixed', top: '24px', right: '24px', zIndex: 9999 }}>
          <Toast
            message={toast.message}
            variant={toast.variant}
            onClose={() => setToast(null)}
          />
        </div>
      )}

      <header className="ceopro-payment-heading">
        <Link to={isCustom ? routePaths.onboardingPlanCustom : routePaths.onboardingPlan}>
          <ArrowLeft className="ceopro-setup-direction-icon" size={14} />
          {t('billing.payment.backToPlans')}
        </Link>
        <h1>{t('billing.payment.title')}</h1>
      </header>

      <div className="ceopro-payment-layout">
        <div>
          <PaymentMethodSelector
            onComplete={completeCheckout}
            loading={isCustom ? customPending : checkout.isPending}
          />
          {!isCustom && (
            <CouponInput
              planId={activePlanDetails.id}
              value={promoCode}
              onChange={setPromoCode}
              disabled={checkout.isPending}
            />
          )}
          {isCustom && (
            <p className="ceopro-preview-notice" role="note">
              The server recalculates your custom price immediately before checkout. A browser-supplied price is never trusted.
            </p>
          )}
        </div>

        <PlanSummaryCard
          plan={activePlanDetails}
          planId={selectedPlan}
          billingPeriod={billingPeriod}
          checkoutMode={checkoutMode}
        />
      </div>
    </OnboardingPageShell>
  );
}
