import { hasAnyRole, normalizeRoles } from '../../auth/permissions/rolePermissions.js';

// backend/src/ai/routers/settings.py's real, seeded role_keys
// (_VALID_ROLE_KEYS) - every tenant's real membership row carries one of
// these, never 'admin' alone: signup itself always assigns 'owner'
// (routers/auth.py), so gating admin-tier actions on 'admin' only meant
// no real account owner could ever invite a teammate or edit company
// settings. _COMPANY_ADMIN_ROLES on the backend is {"owner", "admin"} -
// mirrored here exactly, since the backend is the actual authority (a
// 403 there is the real enforcement; this only controls whether the UI
// offers the action at all).
export const SETTINGS_ROLES = Object.freeze(['owner', 'admin', 'manager', 'accountant', 'staff']);
const ADMIN_TIER_ROLES = Object.freeze(['owner', 'admin']);

export function getSettingsPermissions(roles = []) {
  const normalized = normalizeRoles(roles);
  const role = SETTINGS_ROLES.find((candidate) => normalized.includes(candidate)) || normalized[0] || null;
  const isAdmin = hasAnyRole(roles, ADMIN_TIER_ROLES);
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
    canExportCompany: isAdmin,
    canDeleteCompany: role === 'owner',
  });
}
