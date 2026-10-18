export default function RoleBadge({ role, t }) {
  return <span className={`settings-role-badge is-${role}`}>{['admin', 'editor', 'viewer'].includes(role) ? t(`settings.roles.${role}.label`) : role || t('settings.common.notAvailable')}</span>;
}
