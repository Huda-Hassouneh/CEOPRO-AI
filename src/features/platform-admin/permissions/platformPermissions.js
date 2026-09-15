// Platform roles are never inferred from tenant roles or browser-persisted claims.
export const PLATFORM_ROLES = Object.freeze(['SUPER_ADMIN', 'ADMIN', 'EDITOR', 'VIEWER']);
const read = ['platform.overview.read', 'companies.read', 'users.read', 'subscriptions.read', 'plans.read', 'features.read', 'auditLogs.read'];
const operational = ['companies.update', 'companies.status.manage', 'users.manage', 'subscriptions.manage'];
export const ROLE_PERMISSIONS = Object.freeze({
  VIEWER: Object.freeze([...read]),
  EDITOR: Object.freeze([...read, 'companies.update']),
  ADMIN: Object.freeze([...read, ...operational, 'adminTeam.read']),
  SUPER_ADMIN: Object.freeze([...read, ...operational, 'plans.manage', 'features.manage', 'adminTeam.read', 'adminTeam.invite', 'adminTeam.roles.manage', 'adminTeam.remove', 'platformSettings.read', 'platformSettings.manage']),
});
export const can = (principal, permission) => principal?.status === 'active' && Boolean(ROLE_PERMISSIONS[principal.role]) && (!permission || ROLE_PERMISSIONS[principal.role].includes(permission));
export function requirePermission(principal, permission) {
  if (!can(principal, permission)) throw Object.assign(new Error('forbidden'), { code: 'forbidden' });
}
export function protectLastSuperAdmin(members, target, changes) {
  const losesAccess = changes.remove || (changes.role && changes.role !== 'SUPER_ADMIN') || (changes.status && changes.status !== 'active');
  if (target.role === 'SUPER_ADMIN' && target.status === 'active' && losesAccess && !members.some(m => m.id !== target.id && m.role === 'SUPER_ADMIN' && m.status === 'active')) {
    throw Object.assign(new Error('lastAdmin'), { code: 'lastAdmin' });
  }
}
