import { useQuery } from "@tanstack/react-query";
import { Navigate, useLocation } from "react-router-dom";
import { routePaths } from "../../../app/router/routePaths.js";
import { RoutePending } from "../../../app/router/RoutePending.jsx";
import {
  selectIsAuthenticated,
  useAuthStore
} from "../../auth/store/authStore.js";
import { ADMIN_PREVIEW, platformAdminApi } from "../api/platformAdminApi.js";
import { getPlatformAdminMeQueryKey } from "../api/platformAdminQueryKeys.js";
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import {
  isPlatformPrincipal
} from "../permissions/platformPermissions.js";

const getStatus = (error) =>
  error?.response?.status ?? error?.status ?? error?.statusCode ?? null;

export function PlatformAdminAccessGuard({ children }) {
  const location = useLocation();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const tenantId = useAuthStore((state) => state.tenantId);
  const roleKey = useAuthStore((state) => state.roleKey);
  const user = useAuthStore((state) => state.user);
  const userId = user?.id ?? null;
  const query = useQuery({
    queryKey: getPlatformAdminMeQueryKey({ tenantId, userId, roleKey }),
    queryFn: platformAdminApi.me,
    enabled:
      isHydrated &&
      (ADMIN_PREVIEW || isAuthenticated),
    retry: false,
    staleTime: 30_000
  });

  if (UI_TESTING_MODE) return children;

  if (!isHydrated) {
    return <RoutePending />;
  }

  if (!ADMIN_PREVIEW && !isAuthenticated) {
    return (
      <Navigate
        to={routePaths.login}
        replace
        state={{ from: location }}
      />
    );
  }

  if (query.isPending) {
    return <RoutePending />;
  }

  if (query.isError) {
    const status = getStatus(query.error);

    if (status === 401) {
      return (
        <Navigate
          to={routePaths.login}
          replace
          state={{ from: location }}
        />
      );
    }

    // Fail closed: a tenant-level admin and any unverifiable session never
    // enter the platform administration route tree.
    return <Navigate to={routePaths.dashboard} replace />;
  }

  // The backend /platform-admin/me endpoint is authoritative. It verifies the
  // token's active TenantUser membership belongs to the platform tenant before
  // returning a principal, so customer-tenant admins fail closed with 403.
  if (!isPlatformPrincipal(query.data)) {
    return <Navigate to={routePaths.dashboard} replace />;
  }

  return children;
}
