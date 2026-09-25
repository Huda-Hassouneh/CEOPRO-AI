import { useMemo, useState } from 'react';
import { UserPlus, Users } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import InviteMemberModal from './InviteMemberModal.jsx';
import TeamMemberTable from './TeamMemberTable.jsx';
import { SettingsSection } from './SettingsSection.jsx';
import { useEntitlements } from '../../billing/hooks/useEntitlements.js';
import { FeatureLock } from '../../billing/components/FeatureLock.jsx';

export function TeamSettings({ query, permissions, companyId, locale, t, onNotice }) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const { isLoading: entitlementsLoading, getFeatureState } = useEntitlements();
  const teamEntitlement = getFeatureState('team_members');
  const teamCapacityAvailable = teamEntitlement.included && (teamEntitlement.isUnlimited || !teamEntitlement.isExceeded);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  if (query.isPending) return <Skeleton height="360px" variant="rectangular" />;
  if (query.isError) return <SettingsSection title={t('settings.team.title')}><p className="settings-inline-error">{t('settings.team.loadError')}</p></SettingsSection>;
  const { members = [], invitations = [], capabilities = {} } = query.data;
  const counts = { total: members.length, admin: members.filter((member) => member.role === 'admin').length, editor: members.filter((member) => member.role === 'editor').length, viewer: members.filter((member) => member.role === 'viewer').length, pending: invitations.length };
  const inviteButton = permissions.canInviteMembers ? <Button size="sm" leadingIcon={<UserPlus size={14} />} disabled={entitlementsLoading || !teamCapacityAvailable} onClick={() => setInviteOpen(true)}>{t('settings.team.invite.action')}</Button> : null;
  return <><SettingsSection title={t('settings.team.title')} subtitle={t('settings.team.subtitle')} actions={inviteButton}>
    {!entitlementsLoading && permissions.canInviteMembers && !teamCapacityAvailable && <FeatureLock state={teamEntitlement} compact />}
    {query.data.available && <div className="settings-team-summary">{Object.entries(counts).map(([key, value]) => <div key={key}><strong>{new Intl.NumberFormat(locale).format(value)}</strong><span>{t(`settings.team.summary.${key}`)}</span></div>)}</div>}
    {!query.data.available && <p className="settings-capability-note">{t('settings.team.directoryUnavailable')}</p>}
    {members.length ? <TeamMemberTable members={members} t={t} formatDate={(value) => Number.isNaN(new Date(value).getTime()) ? t('settings.common.notAvailable') : date.format(new Date(value))} /> : <EmptyState icon={<Users size={24} />} title={t('settings.team.emptyTitle')} description={t('settings.team.emptyDescription')} action={inviteButton} />}
    {query.data.available && members.length === 1 && permissions.canInviteMembers && <div className="settings-team-first"><p>{t('settings.team.firstTeam')}</p><Button size="sm" variant="outline" disabled={entitlementsLoading || !teamCapacityAvailable} onClick={() => setInviteOpen(true)}>{t('settings.team.invite.action')}</Button></div>}
    {!capabilities.changeRole && <p className="settings-capability-note">{t(permissions.canManageRoles ? 'settings.team.managementUnavailable' : 'settings.team.readOnly')}</p>}
    <div className="settings-pending"><h3>{t('settings.team.pendingTitle')}</h3>{invitations.length ? <p>{t('settings.team.pendingCount', { count: invitations.length })}</p> : <p>{t(query.data.invitationsAvailable ? 'settings.team.noPending' : 'settings.team.invitationsUnavailable')}</p>}</div>
  </SettingsSection><InviteMemberModal open={inviteOpen && permissions.canInviteMembers && teamCapacityAvailable} capabilities={capabilities} permissions={permissions} onClose={() => setInviteOpen(false)} members={members} invitations={invitations} companyId={companyId} t={t} onNotice={onNotice} /></>;
}
