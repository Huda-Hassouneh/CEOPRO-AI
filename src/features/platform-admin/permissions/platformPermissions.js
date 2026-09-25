// Production platform authorization comes from TenantUser -> SystemRole.permissions.
// The frontend only reflects permissions returned by GET /platform-admin/me;
// the backend remains authoritative.
export const PLATFORM_ROLES = Object.freeze(['owner', 'admin']);

const asPermissions = (principal) => {
  const permissions = principal?.permissions;
  return permissions && typeof permissions === 'object' && !Array.isArray(permissions)
    ? permissions
    : {};
};

export const can = (principal, permission) => {
  if (!principal || principal.status !== 'active') return false;
  if (principal.roleKey !== 'owner' && principal.role !== 'owner') return false;

  const permissions = asPermissions(principal);
  return !permission || permissions.all === true || permissions[permission] === true;
};

export function requirePermission(principal, permission) {
  if (!can(principal, permission)) {
    throw Object.assign(new Error('forbidden'), { code: 'forbidden' });
  }
}

export function protectLastOwner(members, target, changes) {
  const losesAccess =
    changes.remove ||
    (changes.role && changes.role !== 'owner') ||
    (changes.status && changes.status !== 'active');

  if (
    target.role === 'owner' &&
    target.status === 'active' &&
    losesAccess &&
    !members.some(
      (member) => member.id !== target.id && member.role === 'owner' && member.status === 'active',
    )
  ) {
    throw Object.assign(new Error('lastAdmin'), { code: 'lastAdmin' });
  }
}
