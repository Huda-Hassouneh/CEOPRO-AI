import { useEffect, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate
} from "react-router-dom";
import {
  LayoutDashboard,
  Building2,
  Users,
  CreditCard,
  Layers3,
  ShieldCheck,
  ScrollText,
  Settings2,
  UserRound,
  LogOut,
  Menu,
  Bell,
  ChevronDown,
  Globe2
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import Modal from "../../../shared/components/ui/Modal.jsx";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAuthStore } from "../../auth/store/authStore.js";
import { authApi } from "../../auth/api/authApi.js";
import { platformAdminApi } from "../api/platformAdminApi.js";
import { PLATFORM_ROLES } from "../permissions/platformPermissions.js";
import {
  AdminProvider,
  useAdmin,
  useAdminQuery,
  useAdminText
} from "../components/AdminContext.jsx";
import { Badge, Confirmation } from "../components/AdminUI.jsx";
import "../styles/PlatformAdmin.css";

export const adminNavigation = [
  {
    key: "overviewNav",
    path: "",
    icon: LayoutDashboard,
    permission: "platform.overview.read"
  },
  {
    key: "companies",
    path: "companies",
    icon: Building2,
    permission: "companies.read",
    group: "management"
  },
  {
    key: "users",
    path: "users",
    icon: Users,
    permission: "users.read"
  },
  {
    key: "billing",
    path: "billing",
    icon: CreditCard,
    permission: "billing.read",
    group: "product"
  },
  {
    key: "adminTeam",
    path: "admin-team",
    icon: ShieldCheck,
    permission: "adminTeam.read",
    group: "administration"
  },
  {
    key: "auditLogs",
    path: "audit-logs",
    icon: ScrollText,
    permission: "auditLogs.read"
  },
  {
    key: "settings",
    path: "settings",
    icon: Settings2,
    permission: "platformSettings.read"
  }
];

function Shell() {
  const { t, locale, setLocale } = useAdminText();
  const { t: translate } = useI18n();

  const admin = useAdmin();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();

  const [drawer, setDrawer] = useState(false);
  const [logout, setLogout] = useState(false);
  const [busy, setBusy] = useState(false);

  const [notificationActionId, setNotificationActionId] = useState(null);

  const [markingAllRead, setMarkingAllRead] = useState(false);

  useEffect(() => {
    const dismiss = (event) => {
      document.querySelectorAll(".pa-popover[open]").forEach((element) => {
        if (
          event.key === "Escape" ||
          (event.type === "pointerdown" && !element.contains(event.target))
        ) {
          element.removeAttribute("open");

          if (event.key === "Escape") {
            element.querySelector("summary")?.focus();
          }
        }
      });
    };

    document.addEventListener("keydown", dismiss);
    document.addEventListener("pointerdown", dismiss);

    return () => {
      document.removeEventListener("keydown", dismiss);
      document.removeEventListener("pointerdown", dismiss);
    };
  }, []);

  const canReadNotifications = admin.can("notifications.read");

  const notifications = useAdminQuery(
    "notifications",
    { limit: 3 },
    undefined,
    {
      enabled: canReadNotifications,
      refetchInterval: 30_000,
      refetchOnWindowFocus: true
    }
  );

  const unreadNotifications = useAdminQuery(
    "notifications/unread-count",
    {},
    undefined,
    {
      enabled: canReadNotifications,
      refetchInterval: 30_000,
      refetchOnWindowFocus: true
    }
  );

  /*
   * Actual backend:
   *
   * {
   *   success: true,
   *   data: {
   *     items: [...],
   *     nextCursor: null
   *   }
   * }
   */
  const notificationItems = notifications.data?.data?.items ?? [];

  /*
   * Actual backend:
   *
   * {
   *   success: true,
   *   data: {
   *     unreadCount: 0
   *   }
   * }
   */
  const unreadCount = Number(unreadNotifications.data?.data?.unreadCount ?? 0);

  const uiText = (key, fallback) => {
    const value = t(key);

    return value === key || value === `platformAdmin.${key}` ? fallback : value;
  };

  const notificationTitle = (notification) => {
    const translated = translate(
      notification.titleKey,
      notification.payload || {}
    );

    if (translated && translated !== notification.titleKey) {
      return translated;
    }

    return String(notification.eventType || "notification")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  };

  const notificationBody = (notification) => {
    const translated = translate(
      notification.bodyKey,
      notification.payload || {}
    );

    if (translated && translated !== notification.bodyKey) {
      return translated;
    }

    return notification.payload?.failureReason || "";
  };

  const notificationTarget = (notification) => {
    if (notification.resourceType === "subscription") {
      return "/admin/billing?tab=subscriptions";
    }

    if (notification.resourceType === "company" && notification.resourceId) {
      return `/admin/companies/${notification.resourceId}`;
    }

    return "/admin";
  };

  const notificationDate = (value) => {
    if (!value || Number.isNaN(Date.parse(value))) {
      return "";
    }

    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(new Date(value));
  };

  const refreshNotifications = async () => {
    await Promise.all([notifications.refetch(), unreadNotifications.refetch()]);
  };

  const markNotificationRead = async (notificationId) => {
    setNotificationActionId(notificationId);

    try {
      await platformAdminApi.notifications.markRead(notificationId);

      await refreshNotifications();
    } catch {
      admin.notify(uiText("failed", "Action failed"), "error");
    } finally {
      setNotificationActionId(null);
    }
  };

  const archiveNotification = async (notificationId) => {
    setNotificationActionId(notificationId);

    try {
      await platformAdminApi.notifications.archive(notificationId);

      await refreshNotifications();
    } catch {
      admin.notify(uiText("failed", "Action failed"), "error");
    } finally {
      setNotificationActionId(null);
    }
  };

  const markAllNotificationsRead = async () => {
    if (unreadCount <= 0) return;

    setMarkingAllRead(true);

    try {
      await platformAdminApi.notifications.readAll();

      await refreshNotifications();
    } catch {
      admin.notify(uiText("failed", "Action failed"), "error");
    } finally {
      setMarkingAllRead(false);
    }
  };

  const section = adminNavigation.find(
    (item) => item.path && location.pathname.startsWith(`/admin/${item.path}`)
  );

  const pageName =
    section?.key ||
    (location.pathname.includes("/profile")
      ? "profile"
      : location.pathname.includes("/security")
        ? "security"
        : "overviewNav");

  const signOut = async () => {
    setBusy(true);

    try {
      if (!admin.preview) {
        await authApi.logout({});
      }
    } catch {
      /*
       * Local cleanup must still run
       * if revocation is unavailable.
       */
    } finally {
      await platformAdminApi.setPreviewRole(null);

      useAuthStore.getState().clearSession();

      client.removeQueries({
        queryKey: ["platform-admin"]
      });

      setBusy(false);

      navigate("/login", {
        replace: true
      });
    }
  };

  const nav = (
    <>
      <Link to="/admin" className="pa-brand" onClick={() => setDrawer(false)}>
        <span className="pa-brand-mark">
          <Layers3 size={25} />
        </span>

        <span>
          <b>{t("brand")}</b>
          <small>{t("platform")}</small>
        </span>
      </Link>

      <div className="pa-workspace">
        <ShieldCheck size={17} />

        <span>{t("platformScope")}</span>

        <span className="pa-dot" />
      </div>

      <nav aria-label={t("platform")}>
        {adminNavigation
          .filter((item) => admin.can(item.permission))
          .map(({ key, path, icon: Icon, group }) => (
            <div key={key}>
              {group && <p className="pa-nav-group">{t(group)}</p>}

              <NavLink
                end={path === ""}
                to={`/admin${path ? `/${path}` : ""}`}
                onClick={() => setDrawer(false)}
              >
                <Icon size={18} />

                <span>{t(key)}</span>
              </NavLink>
            </div>
          ))}
      </nav>

      <div className="pa-nav-bottom">
        <NavLink to="/admin/profile" onClick={() => setDrawer(false)}>
          <UserRound size={18} />

          {t("profile")}
        </NavLink>

        <button
          type="button"
          onClick={() => {
            setDrawer(false);
            setLogout(true);
          }}
        >
          <LogOut size={18} />

          {t("logout")}
        </button>

        <div className="pa-sidebar-identity">
          <span className="pa-avatar">{admin.principal.name?.slice(0, 1)}</span>

          <div>
            <strong>{admin.principal.name}</strong>

            <small>{t(admin.principal.role)}</small>
          </div>
        </div>
      </div>
    </>
  );

  return (
    <div className="pa-shell">
      <a href="#admin-main" className="pa-skip">
        {t("skip")}
      </a>

      <aside className="pa-sidebar">{nav}</aside>

      <Modal
        className="pa-dialog"
        isOpen={drawer}
        title={t("platform")}
        closeLabel={t("close")}
        onClose={() => setDrawer(false)}
      >
        <div className="pa-mobile-nav">{nav}</div>
      </Modal>

      <div className="pa-body">
        <header className="pa-topbar">
          <button
            className="pa-icon-button pa-mobile-toggle"
            onClick={() => setDrawer(true)}
            aria-label={t("menu")}
          >
            <Menu size={21} />
          </button>

          <div className="pa-breadcrumb">
            <Link to="/admin">{t("platform")}</Link>

            <span>/</span>

            <strong>{t(pageName)}</strong>
          </div>

          <div className="pa-topbar-actions">
            <button
              className="pa-language"
              onClick={() => setLocale(locale === "en" ? "ar" : "en")}
              aria-label={t("language")}
            >
              <Globe2 size={17} />

              <span>{t(locale === "en" ? "arabic" : "english")}</span>
            </button>

            {canReadNotifications && (
              <details className="pa-popover pa-notification-popover">
                <summary aria-label={`${t("notifications")} (${unreadCount})`}>
                  <Bell size={19} />

                  {unreadCount > 0 && <i />}
                </summary>

                <div className="pa-popover-content pa-notification-popover-content">
                  {" "}
                  <div className="pa-notification-popover-heading">
                    <h3>{t("notifications")}</h3>

                    {unreadCount > 0 && (
                      <button
                        type="button"
                        onClick={markAllNotificationsRead}
                        disabled={markingAllRead}
                      >
                        {uiText("markAllRead", "Mark all as read")}
                      </button>
                    )}
                  </div>
                  {notifications.isPending ? (
                    <p>{t("loading")}</p>
                  ) : notifications.isError ? (
                    <p>{uiText("failed", "Failed to load notifications")}</p>
                  ) : notificationItems.length ? (
                    notificationItems.map((notification) => (
                      <div
                        key={notification.id}
                        className={`pa-notification-item${
                          notification.readAt ? "" : " is-unread"
                        }`}
                      >
                        <Link
                          to={notificationTarget(notification)}
                          onClick={(event) => {
                            event.currentTarget
                              .closest("details")
                              ?.removeAttribute("open");

                            if (!notification.readAt) {
                              void markNotificationRead(notification.id);
                            }
                          }}
                        >
                          <b>{notificationTitle(notification)}</b>

                          {notificationBody(notification) && (
                            <small>{notificationBody(notification)}</small>
                          )}

                          <small>
                            {notificationDate(
                              notification.occurredAt || notification.createdAt
                            )}
                          </small>
                        </Link>

                        <button
                          type="button"
                          disabled={notificationActionId === notification.id}
                          onClick={() => archiveNotification(notification.id)}
                        >
                          {uiText("archive", "Archive")}
                        </button>
                      </div>
                    ))
                  ) : (
                    <p>{t("noNotifications")}</p>
                  )}
                </div>
              </details>
            )}

            <details className="pa-popover">
              <summary aria-label={t("identity")}>
                <span className="pa-avatar">
                  {admin.principal.name?.slice(0, 1)}
                </span>

                <span className="pa-topbar-user">
                  <strong>{admin.principal.name}</strong>

                  <small>{t(admin.principal.role)}</small>
                </span>

                <ChevronDown size={14} />
              </summary>

              <div className="pa-popover-content">
                {["profile", "security"].map((key) => (
                  <Link
                    key={key}
                    to={`/admin/${key}`}
                    onClick={(event) =>
                      event.currentTarget
                        .closest("details")
                        ?.removeAttribute("open")
                    }
                  >
                    {t(key)}
                  </Link>
                ))}

                <button onClick={() => setLogout(true)}>{t("logout")}</button>
              </div>
            </details>
          </div>
        </header>

        {admin.preview && (
          <div className="pa-preview">
            <div>
              <b>{t("preview")}</b>

              <span>{t("previewNote")}</span>
            </div>

            <label>
              {t("previewRole")}

              <select
                aria-label={t("previewRole")}
                value={admin.principal.role}
                onChange={(event) => admin.chooseRole(event.target.value)}
              >
                {PLATFORM_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {t(role)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <main id="admin-main" className="pa-main" tabIndex={-1}>
          <Outlet />
        </main>

        <footer className="pa-footer">
          <span>
            {t("brand")} · {t("platform")}
          </span>

          <Badge value={admin.principal.role} />
        </footer>
      </div>

      <Confirmation
        open={logout}
        title={t("logout")}
        busy={busy}
        onClose={() => setLogout(false)}
        onConfirm={signOut}
      >
        <p>{t("logoutNote")}</p>
      </Confirmation>
    </div>
  );
}

export function PlatformAdminLayout() {
  return (
    <AdminProvider>
      <Shell />
    </AdminProvider>
  );
}
