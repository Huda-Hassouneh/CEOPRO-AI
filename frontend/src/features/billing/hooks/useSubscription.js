import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';
import { useEffect, useReducer } from 'react';
import { expireTrialSnapshot } from '../utils/onboardingRouting.js';

export function useSubscription(companyId, options = {}) {
  const query = useQuery({ queryKey: ['subscription', companyId], queryFn: billingApi.getSubscription, enabled: Boolean(companyId), ...options });
  const [, render] = useReducer((n) => n + 1, 0);
  const end = query.data?.accessEndsAt || (query.data?.billingStatus === 'trialing' ? (query.data.trialEndsAtExact || query.data.trialEndsAt) : null);
  const refetch = query.refetch;
  useEffect(() => {
    if (!end) return;
    const delay = Date.parse(end) - Date.now();
    if (!Number.isFinite(delay) || delay <= 0) return;
    const timer = setTimeout(() => { render(); refetch(); }, Math.min(delay + 1, 2147483647));
    return () => clearTimeout(timer);
  }, [end, refetch]);
  return { ...query, data: expireTrialSnapshot(query.data) };
}
