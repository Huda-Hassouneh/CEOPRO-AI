import { Navigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { getOnboardingPathForStep } from '../config/onboardingSteps.js';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingWelcomePage() {
  const currentStep = useOnboardingStore((state) => state.currentStep);
  const isComplete = useOnboardingStore((state) => state.isComplete);
  const onboardingPreviewEnabled = import.meta.env.DEV === true && import.meta.env.VITE_ENABLE_ONBOARDING_PREVIEW === 'true';
  if (onboardingPreviewEnabled) return <Navigate to={routePaths.onboardingRegion} replace />;

  return <Navigate to={isComplete ? routePaths.dashboard : getOnboardingPathForStep(currentStep)} replace />;
}
