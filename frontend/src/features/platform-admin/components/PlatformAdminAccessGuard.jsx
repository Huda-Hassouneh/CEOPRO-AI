import { useQuery } from "@tanstack/react-query";
import { Navigate, useLocation } from "react-router-dom";
import { routePaths } from "../../../app/router/routePaths.js";
import { RoutePending } from "../../../app/router/RoutePending.jsx";
import { selectIsAuthenticated, useAuthStore } from "../../auth/store/authStore.js";
import { platformAdminApi } from "../api/platformAdminApi.js";
import { getPlatformAdminMeQueryKey } from "../api/platformAdminQueryKeys.js";
import { getApiErrorMessage } from "../api/platformAdminErrors.js";
import { isPlatformPrincipal } from "../permissions/platformPermissions.js";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";

export function PlatformAdminAccessGuard({ children }) {
  const location = useLocation();
  const { locale } = useI18n();
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const tenantId = useAuthStore((state) => state.tenantId);
  const roleKey = useAuthStore((state) => state.roleKey);
  const user = useAuthStore((state) => state.user);
  const userId = user?.id ?? null;
  const query = useQuery({
    queryKey: getPlatformAdminMeQueryKey({ tenantId, userId, roleKey }),
    queryFn: platformAdminApi.me,
    enabled: isHydrated && isAuthenticated,
    retry: false,
    staleTime: 30_000
  });

  if (!isHydrated) return <RoutePending />;
  if (!isAuthenticated) return <Navigate to={routePaths.login} replace state={{ from: location }} />;
  if (query.isPending) return <RoutePending />;
  if (query.isError) {
    if (query.error?.response?.status === 401) return <Navigate to={routePaths.login} replace state={{ from: location }} />;
    return <main className="pa-gate" role="alert"><h1>{locale === "ar" ? "تعذر التحقق من صلاحية المنصة" : "Platform access could not be verified"}</h1><p>{getApiErrorMessage(query.error)}</p><a href={routePaths.dashboard}>{locale === "ar" ? "العودة إلى التطبيق" : "Return to the app"}</a></main>;
  }
  if (!isPlatformPrincipal(query.data)) return <main className="pa-gate" role="alert"><h1>{locale === "ar" ? "غير مصرح" : "Access denied"}</h1><p>{getApiErrorMessage({ status: 403 })}</p><a href={routePaths.dashboard}>{locale === "ar" ? "العودة إلى التطبيق" : "Return to the app"}</a></main>;
  return children;
}
