import { useState } from "react";
import {
  Archive,
  Bell,
  CheckCheck,
  Languages,
  Menu,
  Search,
  X
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { useAuthStore } from "../../../features/auth/store/authStore.js";
import { useTenantNotifications } from "../../../features/notifications/hooks/useTenantNotifications.js";
import { getAccountProfile } from "../../../features/onboarding/utils/accountProfile.js";
import Avatar from "../ui/Avatar.jsx";

function notificationTarget(notification) {
  if (notification.resourceType === "custom_plan_quote") {
    const quoteId = notification.resourceId ?? notification.payload?.quoteId;
    if (!quoteId) return null;
    return routePaths.customPlanOffer.replace(
      ":quoteId",
      encodeURIComponent(quoteId)
    );
  }

  return null;
}

function formatNotificationTime(value, locale) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

export default function Topbar({ onMenuClick }) {
  const { t, dir, locale, setLocale } = useI18n();
  const user = useAuthStore((state) => state.user);
  const clearSession = useAuthStore((state) => state.clearSession);
  const navigate = useNavigate();
  const profile = getAccountProfile(user, t);
  const displayProfile =
    import.meta.env.DEV &&
    import.meta.env.VITE_ENABLE_AUTH_PREVIEW === "true" &&
    !user
      ? {
          ...profile,
          personName: "Preview User",
          companyName: "Local development preview",
          email: "preview@localhost",
          initials: "PV"
        }
      : profile;
  const [query, setQuery] = useState("");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const {
    items: notifications,
    unreadCount,
    isLoading: notificationsLoading,
    isError: notificationsError,
    markRead,
    archive,
    readAll,
    archiving,
    markingAllRead
  } = useTenantNotifications({ limit: 5 });

  const openNotification = (notification) => {
    if (!notification.readAt) {
      markRead(notification.id);
    }

    const target = notificationTarget(notification);
    if (target) {
      setNotificationsOpen(false);
      navigate(target);
    }
  };

  const archiveNotification = (notificationId) => {
    archive(notificationId);
  };

  return (
    <header className="business-topbar" dir={dir}>
      <button
        type="button"
        className="business-topbar__menu"
        onClick={onMenuClick}
        aria-label={t("businessShell.mobile.openMenu")}
      >
        <Menu size={20} aria-hidden="true" />
      </button>

      <div className="business-topbar__search">
        <Search size={17} aria-hidden="true" />
        <label className="sr-only" htmlFor="business-global-search">
          {t("businessShell.search.label")}
        </label>
        <input
          id="business-global-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("businessShell.search.placeholder")}
          type="search"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label={t("businessShell.search.clear")}
          >
            <X size={15} />
          </button>
        )}
      </div>

      <div className="business-topbar__actions">
        <button
          type="button"
          className="business-topbar__language"
          onClick={() => setLocale(locale === "en" ? "ar" : "en")}
          aria-label={t("common.languageSwitch")}
        >
          <Languages size={17} aria-hidden="true" />
          <span>
            {locale === "en"
              ? t("common.arabicShort")
              : t("common.englishShort")}
          </span>
        </button>

        <button
          type="button"
          className="business-topbar__icon-button"
          aria-label={t("businessShell.notifications.label")}
          aria-expanded={notificationsOpen}
          aria-controls="business-notifications-popover"
          onClick={() => {
            setNotificationsOpen((open) => !open);
            setProfileOpen(false);
          }}
        >
          <Bell size={18} aria-hidden="true" />
          {unreadCount > 0 && (
            <>
              <span className="business-topbar__unread" aria-hidden="true" />
              <span className="sr-only">
                {t("businessShell.notifications.unreadCount", {
                  count: unreadCount
                })}
              </span>
            </>
          )}
        </button>

        <button
          type="button"
          className="business-topbar__profile"
          aria-label={t("businessShell.profile.label")}
          aria-expanded={profileOpen}
          onClick={() => {
            setProfileOpen((open) => !open);
            setNotificationsOpen(false);
          }}
        >
          <Avatar
            src={displayProfile.avatarUrl}
            alt={displayProfile.personName}
            fallback={displayProfile.initials}
            size="34px"
          />
          <span className="business-topbar__profile-copy">
            <small>{t("businessShell.profile.welcome")}</small>
            <strong>{displayProfile.personName}</strong>
          </span>
          <span className="business-topbar__chevron" aria-hidden="true">
            ⌄
          </span>
        </button>

        {notificationsOpen && (
          <div
            id="business-notifications-popover"
            className="business-topbar__notification-preview"
            role="region"
            aria-label={t("businessShell.notifications.title")}
            aria-live="polite"
          >
            <div className="business-topbar__notification-heading">
              <div>
                <strong>{t("businessShell.notifications.title")}</strong>
                {unreadCount > 0 && (
                  <small>
                    {t("businessShell.notifications.unreadCount", {
                      count: unreadCount
                    })}
                  </small>
                )}
              </div>
              <button
                type="button"
                className="business-topbar__notification-read-all"
                onClick={() => readAll()}
                disabled={unreadCount === 0 || markingAllRead}
              >
                <CheckCheck size={14} aria-hidden="true" />
                <span>{t("businessShell.notifications.markAllRead")}</span>
              </button>
            </div>

            <div className="business-topbar__notification-list">
              {notificationsLoading && (
                <p className="business-topbar__notification-state">
                  {t("businessShell.notifications.loading")}
                </p>
              )}

              {!notificationsLoading && notificationsError && (
                <p className="business-topbar__notification-state is-error">
                  {t("businessShell.notifications.error")}
                </p>
              )}

              {!notificationsLoading &&
                !notificationsError &&
                notifications.length === 0 && (
                  <p className="business-topbar__notification-state">
                    {t("businessShell.notifications.empty")}
                  </p>
                )}

              {!notificationsLoading &&
                !notificationsError &&
                notifications.map((notification) => (
                  <div
                    key={notification.id}
                    className={`business-topbar__notification-item ${
                      notification.readAt ? "" : "is-unread"
                    }`}
                  >
                    <button
                      type="button"
                      className="business-topbar__notification-main"
                      onClick={() => openNotification(notification)}
                    >
                      <strong>
                        {t(notification.titleKey, notification.payload ?? {})}
                      </strong>
                      <span>
                        {t(notification.bodyKey, notification.payload ?? {})}
                      </span>
                      <small>
                        {formatNotificationTime(
                          notification.occurredAt ?? notification.createdAt,
                          locale
                        )}
                      </small>
                    </button>
                    <button
                      type="button"
                      className="business-topbar__notification-archive"
                      onClick={() => archiveNotification(notification.id)}
                      disabled={archiving}
                      aria-label={t("businessShell.notifications.archive")}
                      title={t("businessShell.notifications.archive")}
                    >
                      <Archive size={14} aria-hidden="true" />
                    </button>
                  </div>
                ))}
            </div>
          </div>
        )}

        {profileOpen && (
          <div className="business-topbar__profile-menu" role="menu">
            <strong>{displayProfile.personName}</strong>
            <span>{displayProfile.email}</span>
            <span>{displayProfile.companyName}</span>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                clearSession();
                navigate("/login", { replace: true });
              }}
            >
              {t("businessShell.navigation.logout")}
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
