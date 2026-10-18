import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { IndustryPicker } from '../components/IndustryPicker.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingIndustryPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const industry = useOnboardingStore((state) => state.industry);
  const setIndustry = useOnboardingStore((state) => state.setIndustry);
  const completeStep = useOnboardingStore((state) => state.completeStep);

  const continueToBusiness = () => {
    completeStep(2);
    navigate(routePaths.onboardingBusiness);
  };

  return (
    <OnboardingPageShell step={2} title={t('onboarding.industry.title')} subtitle={t('onboarding.industry.subtitle')}>
      <IndustryPicker value={industry} onChange={setIndustry} />
      <OnboardingActions onBack={() => navigate(routePaths.onboardingRegion)} onContinue={continueToBusiness} disabled={!industry} />
    </OnboardingPageShell>
  );
}
