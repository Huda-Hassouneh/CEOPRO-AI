import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { useEntitlements } from '../hooks/useEntitlements.js';
import { FeatureLock } from './FeatureLock.jsx';

export function FeatureGate({
  featureCode,
  mode = 'access',
  children,
  compact = false,
  fallback,
}) {
  const { isLoading, isError, getFeatureState } = useEntitlements();

  if (isLoading) {
    return fallback ?? <div style={{ padding: 'var(--ceopro-space-4)' }}><Skeleton height="72px" /></div>;
  }

  const state = getFeatureState(featureCode);
  const blocked = isError
    || !state.included
    || (mode === 'consume' && !state.isUnlimited && state.isExceeded);

  if (blocked) {
    return fallback ?? <FeatureLock state={state} compact={compact} reason={isError ? 'notIncluded' : undefined} />;
  }

  return typeof children === 'function' ? children(state) : children;
}
