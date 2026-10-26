import { Navigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { companyApi } from '../../features/settings/api/companyApi.js';
import { useAuthStore } from '../../features/auth/store/authStore.js';
import { useSubscription } from '../../features/billing/hooks/useSubscription.js';
import { getPostSetupPath } from '../../features/billing/utils/onboardingRouting.js';
import { routePaths } from './routePaths.js';
import { RoutePending } from './RoutePending.jsx';

// Pages a company can use before guided setup is finished.
const OPEN_BEFORE_SETUP = ['/onboarding', '/billing', '/settings', '/workspaces', '/connect-data'];

// Sends a company that hasn't finished guided setup to it. If the profile
// can't be loaded the page renders normally - the gate never blocks work.
export function SetupGate({ children }) {
  const { pathname } = useLocation();
  const tenantId = useAuthStore((state) => state.tenantId);
  const open = OPEN_BEFORE_SETUP.some((path) => pathname.startsWith(path)) || pathname.startsWith('/onboarding/plan');
  const query = useQuery({ queryKey: ['settings-company', 'gate'], queryFn: () => companyApi.getCompany(), staleTime: 5 * 60_000, enabled: !open });
  const companyComplete = Boolean(query.data?.company.onboardingCompletedAt);
  const subscriptionQuery = useSubscription(tenantId, { enabled: !open && companyComplete && Boolean(tenantId), staleTime: 60_000 });
  if (!open && (query.isPending || query.isFetching)) return <RoutePending />;
  if (!open && query.data && !companyComplete) return <Navigate to={routePaths.onboarding} replace />;
  if (!open && companyComplete && subscriptionQuery.isPending) return <RoutePending />;
  if (!open && companyComplete && subscriptionQuery.isError) return <Navigate to="/billing" replace />;
  if (!open && companyComplete && subscriptionQuery.data) {
    const destination = getPostSetupPath(subscriptionQuery.data);
    if (destination !== '/dashboard' && destination !== '/market') return <Navigate to={destination} replace />;
  }
  return children;
}
