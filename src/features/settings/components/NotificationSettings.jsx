import { BellOff } from 'lucide-react';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { SettingsSection } from './SettingsSection.jsx';

export function NotificationSettings({ query, t }) {
  if (query.isPending) return <Skeleton height="260px" variant="rectangular" />;
  if (query.isError) return <SettingsSection title={t('settings.notifications.title')}><p className="settings-inline-error">{t('settings.notifications.loadError')}</p></SettingsSection>;
  return <SettingsSection title={t('settings.notifications.title')} subtitle={t('settings.notifications.subtitle')}><EmptyState icon={<BellOff size={23} />} title={t('settings.notifications.unavailableTitle')} description={t('settings.notifications.unavailableDescription')} /></SettingsSection>;
}
