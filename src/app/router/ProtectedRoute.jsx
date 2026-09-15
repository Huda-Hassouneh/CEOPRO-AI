import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore, selectIsAuthenticated } from '../../features/auth/store/authStore.js';
import { RoutePending } from './RoutePending.jsx';

export function ProtectedRoute({ children }) {
  const location = useLocation();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const authPreviewEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_AUTH_PREVIEW === 'true';

  if (!isHydrated) {
    return <RoutePending />;
  }

  if (!isAuthenticated && !authPreviewEnabled) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
