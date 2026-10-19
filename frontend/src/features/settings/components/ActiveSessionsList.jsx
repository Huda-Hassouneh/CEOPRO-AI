import { MonitorSmartphone } from 'lucide-react';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';

export default function ActiveSessionsList({ query, t }) {
  if (query.isPending) return <Skeleton height="140px" variant="rectangular" />;
  if (query.isError) return <p className="settings-inline-error">{t('settings.security.sessionsError')}</p>;
  if (!query.data?.available) return <EmptyState icon={<MonitorSmartphone size={23} />} title={t('settings.security.sessionsUnavailableTitle')} description={t('settings.security.sessionsUnavailableDescription')} />;
  if (!query.data.sessions.length) return <EmptyState icon={<MonitorSmartphone size={23} />} title={t('settings.security.noSessionsTitle')} description={t('settings.security.noSessionsDescription')} />;
  return <ul className="settings-session-list">{query.data.sessions.map((session) => <li key={session.id}><strong>{session.deviceName}</strong>{session.current && <span>{t('settings.security.currentSession')}</span>}{session.lastActiveAt && <small>{session.lastActiveAt}</small>}</li>)}</ul>;
}
