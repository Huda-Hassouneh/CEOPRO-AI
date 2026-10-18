import { Navigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { companyApi } from '../../features/settings/api/companyApi.js';
import { routePaths } from './routePaths.js';

// Pages a company can use before guided setup is finished.
const OPEN_BEFORE_SETUP = ['/onboarding', '/billing', '/settings', '/workspaces'];

// Sends a company that hasn't finished guided setup to it. If the profile
// can't be loaded the page renders normally - the gate never blocks work.
export function SetupGate({ children }) {
  const { pathname } = useLocation();
  const open = OPEN_BEFORE_SETUP.some((path) => pathname.startsWith(path));
  const query = useQuery({ queryKey: ['settings-company', 'gate'], queryFn: () => companyApi.getCompany(), staleTime: 5 * 60_000, enabled: !open });
  if (!open && query.data && !query.data.company.onboardingCompletedAt) {
    return <Navigate to={routePaths.onboarding} replace />;
  }
  return children;
}
