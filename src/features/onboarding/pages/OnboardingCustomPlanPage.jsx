import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { CustomPlanBuilder } from '../../billing/components/CustomPlanBuilder.jsx';
import { PlanSummaryCard } from '../../billing/components/PlanSummaryCard.jsx';
import { PREVIEW_CUSTOM_QUOTE } from '../../billing/config/billingPreviewData.js';
import { useCustomPlanQuote } from '../../billing/hooks/useCustomPlanQuote.js';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingCustomPlanPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const customPlan = useOnboardingStore((state) => state.customPlan);
  const billingPeriod = useOnboardingStore((state) => state.billingPeriod);
  const updateCustomPlan = useOnboardingStore((state) => state.updateCustomPlan);
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const { data: quote = PREVIEW_CUSTOM_QUOTE } = useCustomPlanQuote(customPlan);

  return (
    <OnboardingPageShell wide step={5} title={t('billing.custom.title')} subtitle={t('billing.custom.subtitle')}>
      <div className="ceopro-custom-plan-layout">
        <CustomPlanBuilder configuration={customPlan} onChange={updateCustomPlan} />
        <PlanSummaryCard planId="custom" customPlan={customPlan} quote={quote} billingPeriod={billingPeriod} />
      </div>
      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingPlan)}
        onContinue={() => { setPlanChoice('custom', 'paid'); navigate(routePaths.onboardingPlanPayment); }}
      />
    </OnboardingPageShell>
  );
}
