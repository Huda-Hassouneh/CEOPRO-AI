import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

const missingState = (featureCode) => ({
  featureCode,
  included: false,
  type: null,
  aggregationType: null,
  resetCycle: null,
  currentUsage: 0,
  limit: null,
  remaining: null,
  isUnlimited: false,
  isExceeded: false,
  feature: null,
});

export function useEntitlements() {
  const query = useQuery({
    queryKey: ['subscription', 'usage'],
    queryFn: billingApi.getSubscriptionUsage,
    retry: false,
    staleTime: 30_000,
  });

  const entitlementsByCode = useMemo(() => {
    const map = new Map();
    for (const entitlement of query.data?.entitlements ?? []) {
      if (entitlement.feature_code) map.set(entitlement.feature_code, entitlement);
    }
    return map;
  }, [query.data]);

  const getFeatureState = useCallback((featureCode) => {
    const entitlement = entitlementsByCode.get(featureCode);
    if (!entitlement) return missingState(featureCode);
    const feature = query.data?.features?.[featureCode] ?? {};
    const limit = entitlement.limit ?? null;
    const currentUsage = Number(entitlement.current_usage ?? 0);
    const remaining = entitlement.remaining == null
      ? null
      : Number(entitlement.remaining);

    return {
      featureCode,
      included: true,
      type: entitlement.type ?? feature.type ?? null,
      aggregationType: entitlement.aggregation_type ?? feature.aggregation_type ?? null,
      resetCycle: entitlement.reset_cycle ?? feature.reset_cycle ?? null,
      currentUsage,
      limit,
      remaining,
      isUnlimited: Boolean(entitlement.is_unlimited ?? limit === null),
      isExceeded: Boolean(entitlement.is_exceeded ?? (limit !== null && currentUsage >= limit)),
      periodStart: query.data?.periodStart ?? null,
      periodEnd: query.data?.renewsAt ?? null,
      feature: {
        ...feature,
        name: entitlement.name ?? feature.name,
        name_ar: entitlement.name_ar ?? feature.name_ar,
        unit: entitlement.unit ?? feature.unit,
        unit_ar: entitlement.unit_ar ?? feature.unit_ar,
      },
    };
  }, [entitlementsByCode, query.data]);

  const hasFeature = useCallback(
    (featureCode) => getFeatureState(featureCode).included,
    [getFeatureState],
  );

  const canConsume = useCallback((featureCode) => {
    const state = getFeatureState(featureCode);
    return state.included && (state.isUnlimited || !state.isExceeded);
  }, [getFeatureState]);

  return {
    ...query,
    getFeatureState,
    hasFeature,
    canConsume,
  };
}
