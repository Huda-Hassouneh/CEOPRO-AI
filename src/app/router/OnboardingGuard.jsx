import { Navigate, useLocation } from 'react-router-dom';
import { useOnboardingStore } from '../../features/onboarding/store/onboardingStore.js';
import { getOnboardingPathForStep } from '../../features/onboarding/config/onboardingSteps.js';
import { routePaths } from './routePaths.js';

export function OnboardingGuard({ children, requiredStep = 1 }) {
  const location = useLocation();
  const highestCompletedStep = useOnboardingStore((state) => state.highestCompletedStep);
  const step5Completed = useOnboardingStore((state) => state.step5Completed);
  const isComplete = useOnboardingStore((state) => state.isComplete);

  const onboardingPreviewEnabled = import.meta.env.DEV === true && import.meta.env.VITE_ENABLE_ONBOARDING_PREVIEW === 'true';
  if (onboardingPreviewEnabled) return children;

  if (isComplete) {
    return <Navigate to={routePaths.dashboard} replace />;
  }

  const highestAccessibleStep = Math.min(6, highestCompletedStep + 1);
  if (requiredStep > highestAccessibleStep || (requiredStep === 6 && !step5Completed)) {
    return <Navigate to={getOnboardingPathForStep(highestAccessibleStep)} replace state={{ from: location }} />;
  }

  return children;
}
