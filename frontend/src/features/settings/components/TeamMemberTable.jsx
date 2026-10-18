import Avatar from '../../../shared/components/ui/Avatar.jsx';
import RoleBadge from './RoleBadge.jsx';

export default function TeamMemberTable({ members, t, formatDate }) {
  return <div className="settings-team-table-wrap"><table className="settings-team-table"><thead><tr><th scope="col">{t('settings.team.columns.member')}</th><th scope="col">{t('settings.team.columns.email')}</th><th scope="col">{t('settings.team.columns.role')}</th><th scope="col">{t('settings.team.columns.status')}</th><th scope="col">{t('settings.team.columns.joined')}</th></tr></thead><tbody>{members.map((member) => {
    const fallback = member.name?.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
    return <tr key={member.id}><td><span className="settings-team-member"><Avatar src={member.avatarUrl} alt={member.name || member.email} fallback={fallback} size="34px" /><span><strong>{member.name || t('settings.common.notAvailable')}</strong>{member.isCurrentUser && <small>{t('settings.team.you')}</small>}</span></span></td><td>{member.email || t('settings.common.notAvailable')}</td><td><RoleBadge role={member.role} t={t} /></td><td><span className={`settings-member-status is-${member.status}`}>{member.status ? t(`settings.team.status.${member.status}`) : t('settings.common.notAvailable')}</span></td><td>{member.joinedAt ? formatDate(member.joinedAt) : t('settings.common.notAvailable')}</td></tr>;
  })}</tbody></table></div>;
}
