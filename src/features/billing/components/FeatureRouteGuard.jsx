import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { useEntitlements } from '../hooks/useEntitlements.js';
import { FeatureLock } from './FeatureLock.jsx';

export function FeatureRouteGuard({ featureCodes, children }) {
  const { isLoading, isError, getFeatureState } = useEntitlements();
  const codes = Array.isArray(featureCodes) ? featureCodes : [featureCodes];

  if (isLoading) {
    return (
      <div className="ceopro-feature-route-loading" style={{ padding: 'var(--ceopro-space-6)' }}>
        <Skeleton height="180px" variant="rectangular" />
      </div>
    );
  }

  if (isError) {
    return <FeatureLock state={{ featureCode: codes[0], included: false }} />;
  }

  for (const code of codes) {
    const state = getFeatureState(code);
    if (!state.included) return <FeatureLock state={state} />;
  }

  return children;
}
