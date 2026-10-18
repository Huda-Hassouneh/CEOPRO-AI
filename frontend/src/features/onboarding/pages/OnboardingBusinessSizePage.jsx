import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { BusinessSizeForm } from '../components/BusinessSizeForm.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingBusinessSizePage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const businessSize = useOnboardingStore((state) => state.businessSize);
  const annualRevenue = useOnboardingStore((state) => state.annualRevenue);
  const setBusinessProfile = useOnboardingStore((state) => state.setBusinessProfile);
  const completeStep = useOnboardingStore((state) => state.completeStep);

  const update = (next) => setBusinessProfile({ businessSize, annualRevenue, ...next });

  return (
    <OnboardingPageShell step={3} title={t('onboarding.business.title')} subtitle={t('onboarding.business.subtitle')}>
      <BusinessSizeForm
        businessSize={businessSize}
        annualRevenue={annualRevenue}
        onBusinessSizeChange={(value) => update({ businessSize: value })}
        onAnnualRevenueChange={(value) => update({ annualRevenue: value })}
      />
      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingIndustry)}
        onContinue={() => { completeStep(3); navigate(routePaths.onboardingObjectives); }}
        disabled={!businessSize || !annualRevenue}
      />
    </OnboardingPageShell>
  );
}
