import { usePlans } from './usePlans.js';

// The free-trial length new companies get, from the live plan catalog.
export function useTrialDays() {
  const { data } = usePlans();
  return data?.plans?.find((plan) => plan.trialDays > 0)?.trialDays || 0;
}
