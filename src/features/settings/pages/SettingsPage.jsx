import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Tabs from '../../../shared/components/ui/Tabs.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import ProfileForm from '../components/ProfileForm.jsx';
import { CompanySettings } from '../components/CompanySettings.jsx';
import { TeamSettings } from '../components/TeamSettings.jsx';
import { NotificationSettings } from '../components/NotificationSettings.jsx';
import { PreferenceSettings } from '../components/PreferenceSettings.jsx';
import { SecuritySettings } from '../components/SecuritySettings.jsx';
import { useProfile } from '../hooks/useProfile.js';
import { useCompany } from '../hooks/useCompany.js';
import { useTeamMembers } from '../hooks/useTeamMembers.js';
import { useNotificationPreferences } from '../hooks/useNotificationPreferences.js';
import { getSettingsPermissions } from '../permissions/settingsPermissions.js';
import '../styles/Settings.css';

const tabIds = ['profile', 'company', 'team', 'notifications', 'preferences', 'security'];

export default function SettingsPage() {
  const { t, locale, dir, setLocale } = useI18n();
  const user = useAuthStore((state) => state.user);
  const roles = useAuthStore((state) => state.roles);
  const companyId = useAuthStore((state) => state.tenantId);
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get('tab');
  const activeTab = tabIds.includes(requestedTab) ? requestedTab : 'profile';
  const permissions = useMemo(() => getSettingsPermissions(roles), [roles]);
  const [notice, setNotice] = useState(null);
  const profileQuery = useProfile(user);
  const companyQuery = useCompany({ user, companyId });
  const teamQuery = useTeamMembers({ user, roles, companyId });
  const notificationQuery = useNotificationPreferences(companyId);
  const showNotice = (variant, message) => setNotice({ variant, message });
  const tabs = [
    { id: 'profile', label: t('settings.tabs.profile'), content: <ProfileForm query={profileQuery} t={t} onNotice={showNotice} /> },
    { id: 'company', label: t('settings.tabs.company'), content: <CompanySettings query={companyQuery} permissions={permissions} t={t} /> },
    { id: 'team', label: t('settings.tabs.team'), content: <TeamSettings query={teamQuery} permissions={permissions} companyId={companyId} locale={locale} t={t} onNotice={showNotice} /> },
    { id: 'notifications', label: t('settings.tabs.notifications'), content: <NotificationSettings query={notificationQuery} t={t} /> },
    { id: 'preferences', label: t('settings.tabs.preferences'), content: <PreferenceSettings locale={locale} setLocale={setLocale} t={t} /> },
    { id: 'security', label: t('settings.tabs.security'), content: <SecuritySettings t={t} onNotice={showNotice} /> },
  ];
  return <div className="settings-workspace" dir={dir}><PageHeader title={t('settings.page.title')} subtitle={t('settings.page.subtitle')} /><Tabs className="settings-workspace-tabs" tabs={tabs} activeTab={activeTab} onChange={(tab) => setParams((previous) => { const next = new URLSearchParams(previous); next.set('tab', tab); return next; })} ariaLabel={t('settings.tabs.label')} />{notice && <div className="settings-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}</div>;
}
