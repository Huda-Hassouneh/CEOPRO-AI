export const PLATFORM_ADMIN_ME_QUERY_KEY = Object.freeze([
  "platform-admin",
  "me"
]);

export const getPlatformAdminMeQueryKey = ({ tenantId, userId, roleKey } = {}) => [
  ...PLATFORM_ADMIN_ME_QUERY_KEY,
  tenantId || "no-tenant",
  userId || "no-user",
  roleKey || "no-role"
];
