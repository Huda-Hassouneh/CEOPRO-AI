import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { PaymentMethodSelector } from '../../billing/components/PaymentMethodSelector.jsx';
import { PlanSummaryCard } from '../../billing/components/PlanSummaryCard.jsx';
import { PREVIEW_CUSTOM_QUOTE } from '../../billing/config/billingPreviewData.js';
import { useCheckout } from '../../billing/hooks/useCheckout.js';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingPaymentPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [method, setMethod] = useState('card');
  const selectedPlan = useOnboardingStore((state) => state.selectedPlan) || 'pro';
  const customPlan = useOnboardingStore((state) => state.customPlan);
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const checkoutMode = useOnboardingStore((state) => state.checkoutMode);
  const checkout = useCheckout();

  const completePreview = async () => {
    const result = await checkout.mutateAsync({ plan: selectedPlan, billingPeriod, checkoutMode, method, preview: true });
    navigate(result.status === 'preview_succeeded' ? routePaths.onboardingPlanSuccess : routePaths.onboardingPlanFailed);
  };

  return (
    <OnboardingPageShell wide showProgress={false}>
      <header className="ceopro-payment-heading">
        <Link to={routePaths.onboardingPlan}><ArrowLeft className="ceopro-setup-direction-icon" size={14} />{t('billing.payment.backToPlans')}</Link>
        <h1>{t('billing.payment.title')}</h1>
      </header>
      <div className="ceopro-payment-layout">
        <PaymentMethodSelector method={method} onMethodChange={setMethod} onComplete={completePreview} loading={checkout.isPending} />
        <PlanSummaryCard planId={selectedPlan} customPlan={customPlan} quote={PREVIEW_CUSTOM_QUOTE} billingPeriod={billingPeriod} checkoutMode={checkoutMode} />
      </div>
    </OnboardingPageShell>
  );
}
