import { Navigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { getOnboardingPathForStep } from '../config/onboardingSteps.js';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingWelcomePage() {
  const currentStep = useOnboardingStore((state) => state.currentStep);
  const isComplete = useOnboardingStore((state) => state.isComplete);
  return <Navigate to={isComplete ? routePaths.dashboard : getOnboardingPathForStep(currentStep)} replace />;
}
