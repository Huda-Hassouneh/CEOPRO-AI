export const normalizeRoles = (roles = []) => roles.map((role) => String(role).trim().toLowerCase()).filter(Boolean);

export const hasAnyRole = (roles, allowed) => {
  const normalizedRoles = normalizeRoles(roles);
  const normalizedAllowed = normalizeRoles(allowed);
  return normalizedAllowed.some((role) => normalizedRoles.includes(role));
};
