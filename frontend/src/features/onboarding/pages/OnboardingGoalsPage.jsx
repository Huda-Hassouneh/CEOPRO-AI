import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { GoalsMultiSelect } from '../components/GoalsMultiSelect.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingGoalsPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const objectives = useOnboardingStore((state) => state.objectives);
  const toggleObjective = useOnboardingStore((state) => state.toggleObjective);
  const completeStep = useOnboardingStore((state) => state.completeStep);

  return (
    <OnboardingPageShell step={4} title={t('onboarding.objectives.title')} subtitle={t('onboarding.objectives.subtitle')}>
      <GoalsMultiSelect values={objectives} onToggle={toggleObjective} />
      <OnboardingActions
        onBack={() => navigate(routePaths.onboardingBusiness)}
        onContinue={() => { completeStep(4); navigate(routePaths.onboardingPlan); }}
        disabled={objectives.length === 0}
      />
    </OnboardingPageShell>
  );
}
