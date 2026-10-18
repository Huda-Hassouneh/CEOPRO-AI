import { hasAnyRole, normalizeRoles } from '../../auth/permissions/rolePermissions.js';

export const SETTINGS_ROLES = Object.freeze(['admin', 'editor', 'viewer']);

export function getSettingsPermissions(roles = []) {
  const normalized = normalizeRoles(roles);
  const role = SETTINGS_ROLES.find((candidate) => normalized.includes(candidate)) || normalized[0] || null;
  const isAdmin = hasAnyRole(roles, ['admin']);
  return Object.freeze({
    role,
    canManageOwnProfile: true,
    canManageOwnNotifications: true,
    canManageOwnPreferences: true,
    canManageOwnSecurity: true,
    canViewCompany: true,
    canEditCompany: isAdmin,
    canViewTeam: true,
    canInviteMembers: isAdmin,
    canManageRoles: isAdmin,
    canRemoveMembers: isAdmin,
  });
}
