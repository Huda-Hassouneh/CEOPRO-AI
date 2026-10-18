import Avatar from '../../../shared/components/ui/Avatar.jsx';
import RoleBadge from './RoleBadge.jsx';
import { useChangeMemberRole, useRemoveMember } from '../hooks/useManageTeamMember.js';

export const TEAM_ROLES = ['owner', 'admin', 'manager', 'accountant', 'staff'];

export default function TeamMemberTable({ members, t, formatDate, canManage = false, onNotice }) {
  const changeRole = useChangeMemberRole();
  const removeMember = useRemoveMember();
  const busy = changeRole.isPending || removeMember.isPending;
  const failure = (error) => error?.response?.data?.detail || t('settings.team.manage.failed');

  const onRoleChange = async (member, role) => {
    if (busy || role === member.role) return;
    try {
      await changeRole.mutateAsync({ tenantUserId: member.id, role });
      onNotice?.('success', t('settings.team.manage.roleChanged', { name: member.name || member.email }));
    } catch (error) {
      onNotice?.('error', failure(error));
    }
  };
  const onRemove = async (member) => {
    if (busy || !globalThis.confirm(t('settings.team.manage.confirmRemove', { name: member.name || member.email }))) return;
    try {
      await removeMember.mutateAsync({ tenantUserId: member.id });
      onNotice?.('success', t('settings.team.manage.removed', { name: member.name || member.email }));
    } catch (error) {
      onNotice?.('error', failure(error));
    }
  };

  return <div className="settings-team-table-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}><table className="settings-team-table"><thead><tr><th scope="col">{t('settings.team.columns.member')}</th><th scope="col">{t('settings.team.columns.email')}</th><th scope="col">{t('settings.team.columns.role')}</th><th scope="col">{t('settings.team.columns.status')}</th><th scope="col">{t('settings.team.columns.joined')}</th>{canManage && <th scope="col">{t('settings.team.columns.actions')}</th>}</tr></thead><tbody>{members.map((member) => {
    const fallback = member.name?.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
    return <tr key={member.id}><td><span className="settings-team-member"><Avatar src={member.avatarUrl} alt={member.name || member.email} fallback={fallback} size="34px" /><span><strong>{member.name || t('settings.common.notAvailable')}</strong>{member.isCurrentUser && <small>{t('settings.team.you')}</small>}</span></span></td><td>{member.email || t('settings.common.notAvailable')}</td><td>{canManage && !member.isCurrentUser
      ? <select className="settings-team-role-select" value={member.role} disabled={busy} onChange={(event) => onRoleChange(member, event.target.value)} aria-label={t('settings.team.manage.roleFor', { name: member.name || member.email })}>{TEAM_ROLES.map((role) => <option key={role} value={role}>{t(`settings.roles.${role}.label`)}</option>)}</select>
      : <RoleBadge role={member.role} t={t} />}</td><td><span className={`settings-member-status is-${member.status}`}>{member.status ? t(`settings.team.status.${member.status}`) : t('settings.common.notAvailable')}</span></td><td>{member.joinedAt ? formatDate(member.joinedAt) : t('settings.common.notAvailable')}</td>{canManage && <td>{!member.isCurrentUser && <button type="button" className="settings-team-remove" disabled={busy} onClick={() => onRemove(member)}>{t('settings.team.manage.remove')}</button>}</td>}</tr>;
  })}</tbody></table></div>;
}
