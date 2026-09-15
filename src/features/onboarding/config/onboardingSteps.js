import { routePaths } from '../../../app/router/routePaths.js';

export const ONBOARDING_STEP_COUNT = 6;

export const onboardingStepPaths = Object.freeze({
  1: routePaths.onboardingRegion,
  2: routePaths.onboardingIndustry,
  3: routePaths.onboardingBusiness,
  4: routePaths.onboardingObjectives,
  5: routePaths.onboardingPlan,
  6: routePaths.onboardingConnectData,
});

export const getOnboardingPathForStep = (step) => onboardingStepPaths[Math.min(6, Math.max(1, step))];
