import { LockKeyhole } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAuthStore } from "../../../features/auth/store/authStore.js";
import { useEntitlements } from "../../../features/billing/hooks/useEntitlements.js";
import {
  businessPrimaryNavigation,
  businessSecondaryNavigation
} from "../../config/businessNavigation.js";
import { authApi } from "../../../features/auth/api/authApi.js";
import { useState } from "react";
import { UI_TESTING_MODE } from "../../config/uiTestingMode.js";

const isActivePath = (pathname, path) =>
  path && (pathname === path || pathname.startsWith(`${path}/`));

export default function Sidebar({ open = false, onClose }) {
  const { t, dir } = useI18n();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const {
    isLoading: entitlementsLoading,
    isError: entitlementsError,
    getFeatureState
  } = useEntitlements();

  const goTo = async (item) => {
    if (item.key === "logout") {
      if (isLoggingOut) return;

      setIsLoggingOut(true);
      try {
        await authApi.logout();
      } catch (err) {
        console.error("Logout request failed:", err);
      } finally {
        // Clear the local session even if the server request fails.
        clearSession();
        onClose?.();
        navigate("/login", { replace: true });
      }
      return;
    }

    if (item.path) navigate(item.path);
    onClose?.();
  };

  const renderItem = (item) => {
    const Icon = item.icon;
    const active = isActivePath(pathname, item.path);
    const locked = Boolean(
      !UI_TESTING_MODE &&
      item.featureCode &&
      !entitlementsLoading &&
      !getFeatureState(item.featureCode).included
    );

    return (
      <button
        key={item.key}
        type="button"
        disabled={(item.key === "logout" && isLoggingOut) || locked}
        aria-busy={item.key === "logout" ? isLoggingOut : undefined}
        className={`business-sidebar__item${active ? " is-active" : ""}${locked ? " is-locked" : ""}${item.key === "logout" ? " is-danger" : ""}`}
        aria-current={active ? "page" : undefined}
        onClick={() => goTo(item)}
      >
        <Icon size={18} aria-hidden="true" />
        {item.key === "logout" && isLoggingOut ? (
          t("common.loggingOut")
        ) : (
          <span>{t(item.labelKey)}</span>
        )}
        <span></span>
        {locked && (
          <LockKeyhole
            className="business-sidebar__lock"
            size={14}
            aria-hidden="true"
          />
        )}
        {/* keep your existing lock icon */}
      </button>
    );
  };

  return (
    <aside
      className={`business-sidebar${open ? " is-open" : ""}`}
      aria-label={t("businessShell.navigation.label")}
      dir={dir}
    >
      <div className="business-sidebar__brand">
        <span className="business-sidebar__brand-mark" aria-hidden="true">
          C
        </span>
        <span>
          <strong>CEO PRO</strong>
          <small>{t("businessShell.brandSubtitle")}</small>
        </span>
      </div>
      <nav
        className="business-sidebar__nav"
        aria-label={t("businessShell.navigation.primary")}
      >
        {businessPrimaryNavigation.map(renderItem)}
      </nav>
      <nav
        className="business-sidebar__nav business-sidebar__nav--secondary"
        aria-label={t("businessShell.navigation.secondary")}
      >
        {businessSecondaryNavigation.map(renderItem)}
      </nav>
    </aside>
  );
}
