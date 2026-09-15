import { PlatformAdminLayout } from './layout/PlatformAdminLayout.jsx';
import { Permission, Forbidden } from './components/AdminUI.jsx';
import { OverviewPage } from './pages/OverviewPage.jsx';
import { DirectoryPage } from './pages/DirectoryPage.jsx';
import { DetailPage } from './pages/DetailPage.jsx';
import { PlansPage, PlanDetailPage, FeaturesPage } from './pages/PlansPage.jsx';
import { AdminTeamPage } from './pages/AdminTeamPage.jsx';
import { AuditLogsPage } from './pages/AuditLogsPage.jsx';
import { PlatformSettingsPage } from './pages/SettingsPage.jsx';
import { ProfilePage, SecurityPage } from './pages/AccountPages.jsx';

const guarded = (permission, element) => <Permission permission={permission}>{element}</Permission>;
export const platformAdminRoute = {
  path: '/admin', element: <PlatformAdminLayout />, children: [
    { index: true, element: guarded('platform.overview.read', <OverviewPage />) },
    ...['companies', 'users', 'subscriptions'].flatMap(domain => [
      { path: domain, element: guarded(`${domain}.read`, <DirectoryPage key={domain} domain={domain} />) },
      { path: `${domain}/:id`, element: guarded(`${domain}.read`, <DetailPage key={domain} domain={domain} />) },
    ]),
    { path: 'plans', element: guarded('plans.read', <PlansPage />) },
    { path: 'plans/:id', element: guarded('plans.read', <PlanDetailPage />) },
    { path: 'plans/:id/edit', element: guarded('plans.manage', <PlanDetailPage editing />) },
    { path: 'features', element: guarded('features.read', <FeaturesPage />) },
    { path: 'admin-team', element: guarded('adminTeam.read', <AdminTeamPage />) },
    { path: 'audit-logs', element: guarded('auditLogs.read', <AuditLogsPage />) },
    { path: 'settings', element: guarded('platformSettings.read', <PlatformSettingsPage />) },
    { path: 'profile', element: <ProfilePage /> },
    { path: 'security', element: <SecurityPage /> },
    { path: '*', element: <Forbidden notFound /> },
  ],
};
