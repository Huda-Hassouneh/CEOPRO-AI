import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore, selectIsAuthenticated } from '../../features/auth/store/authStore.js';
import { needsEmailVerification } from '../../features/auth/sessionKeeper.js';
import { routePaths } from './routePaths.js';
import { RoutePending } from './RoutePending.jsx';
import { SetupGate } from './SetupGate.jsx';
import { PlanGate } from './PlanGate.jsx';

export function ProtectedRoute({ children }) {
  const location = useLocation();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const mustVerifyEmail = useAuthStore((state) => state.emailVerificationBlocked || needsEmailVerification(state.accessToken));

  if (!isHydrated) {
    return <RoutePending />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (mustVerifyEmail) {
    return <Navigate to={routePaths.verifyEmail} replace />;
  }

  return <SetupGate><PlanGate>{children}</PlanGate></SetupGate>;
}
