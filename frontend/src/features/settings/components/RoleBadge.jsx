const KNOWN_ROLES = ['owner', 'admin', 'manager', 'accountant', 'staff', 'editor', 'viewer'];

export default function RoleBadge({ role, t }) {
  return <span className={`settings-role-badge is-${role}`}>{KNOWN_ROLES.includes(role) ? t(`settings.roles.${role}.label`) : role || t('settings.common.notAvailable')}</span>;
}
