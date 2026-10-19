import { Navigate, useLocation } from 'react-router-dom';
import { routePaths } from './routePaths.js';
import { useAuthStore, selectIsAuthenticated } from '../../features/auth/store/authStore.js';
import { getPostLoginDestination } from '../../features/auth/utils/authRouting.js';
import { RoutePending } from './RoutePending.jsx';

export function GuestRoute({ children }) {
  const location = useLocation();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);

  if (!isHydrated) {
    return <RoutePending />;
  }

  if (isAuthenticated) {
    return <Navigate to={getPostLoginDestination(location.state) || routePaths.dashboard} replace />;
  }

  return children;
}
