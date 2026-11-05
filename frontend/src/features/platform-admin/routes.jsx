import { lazy, Suspense } from "react";
import { Navigate } from "react-router-dom";
import { RoutePending } from "../../app/router/RoutePending.jsx";
import { Permission, Forbidden } from "./components/AdminUI.jsx";
import { PlatformAdminAccessGuard } from "./components/PlatformAdminAccessGuard.jsx";

// The Platform Owner console is only for platform staff: load its layout and
// screens on first visit instead of shipping them in every customer's initial
// bundle, and keep them out of the customer app's idle prefetch. The access
// guard stays eager so authorization runs before any console code is fetched.
const named = (load, name) => {
  const Lazy = lazy(() => load().then((m) => ({ default: m[name] })));
  return function AdminScreen(props) {
    return <Suspense fallback={<RoutePending />}><Lazy {...props} /></Suspense>;
  };
};
const PlatformAdminLayout = named(() => import("./layout/PlatformAdminLayout.jsx"), "PlatformAdminLayout");
const OverviewPage = named(() => import("./pages/OverviewPage.jsx"), "OverviewPage");
const DirectoryPage = named(() => import("./pages/DirectoryPage.jsx"), "DirectoryPage");
const DetailPage = named(() => import("./pages/DetailPage.jsx"), "DetailPage");
const AdminTeamPage = named(() => import("./pages/AdminTeamPage.jsx"), "AdminTeamPage");
const AuditLogsPage = named(() => import("./pages/AuditLogsPage.jsx"), "AuditLogsPage");
const PlatformSettingsPage = named(() => import("./pages/SettingsPage.jsx"), "PlatformSettingsPage");
const ProfilePage = named(() => import("./pages/AccountPages.jsx"), "ProfilePage");
const SecurityPage = named(() => import("./pages/AccountPages.jsx"), "SecurityPage");
const BillingManagementPage = named(() => import("./pages/BillingManagementPage.jsx"), "BillingManagementPage");

const guarded = (permission, element) => (
  <Permission permission={permission}>{element}</Permission>
);
export const platformAdminRoute = {
  path: "/admin",
  element: (
    <PlatformAdminAccessGuard>
      <PlatformAdminLayout />
    </PlatformAdminAccessGuard>
  ),
  children: [
    {
      index: true,
      element: guarded("platform.overview.read", <OverviewPage />)
    },
    ...["companies", "users"].flatMap((domain) => [
      {
        path: domain,
        element: guarded(
          `${domain}.read`,
          <DirectoryPage key={domain} domain={domain} />
        )
      },
      {
        path: `${domain}/:id`,
        element: guarded(
          `${domain}.read`,
          <DetailPage key={domain} domain={domain} />
        )
      }
    ]),
    {
      path: "billing",
      element: guarded("billing.read", <BillingManagementPage />)
    },
    {
      path: "subscriptions/*",
      element: <Navigate to="/admin/billing" replace />
    },
    { path: "plans/*", element: <Navigate to="/admin/billing" replace /> },
    { path: "features/*", element: <Navigate to="/admin/billing" replace /> },
    {
      path: "admin-team",
      element: guarded("adminTeam.read", <AdminTeamPage />)
    },
    {
      path: "audit-logs",
      element: guarded("auditLogs.read", <AuditLogsPage />)
    },
    {
      path: "settings",
      element: guarded("platformSettings.read", <PlatformSettingsPage />)
    },
    { path: "profile", element: <ProfilePage /> },
    { path: "security", element: <SecurityPage /> },
    { path: "*", element: <Forbidden notFound /> }
  ]
};
