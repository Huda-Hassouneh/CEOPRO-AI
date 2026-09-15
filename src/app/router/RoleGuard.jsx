import { Navigate, useLocation } from 'react-router-dom';
import { routePaths } from './routePaths.js';
import { useAuthStore, selectIsAuthenticated } from '../../features/auth/store/authStore.js';
import { RoutePending } from './RoutePending.jsx';
import { hasAnyRole } from '../../features/auth/permissions/rolePermissions.js';

export function RoleGuard({ allowed = ['admin'], children }) {
  const location = useLocation();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const roles = useAuthStore((state) => state.roles);

  if (!isHydrated) {
    return <RoutePending />;
  }

  if (!isAuthenticated) {
    return <Navigate to={routePaths.login} replace state={{ from: location }} />;
  }

  if (!hasAnyRole(roles, allowed)) {
    return <Navigate to={routePaths.dashboard} replace />;
  }

  return children;
}
